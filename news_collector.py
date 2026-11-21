"""Collect article metadata from publisher-provided RSS feeds."""
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import urlparse
import feedparser
import requests
from bs4 import BeautifulSoup
from urllib.robotparser import RobotFileParser

SOURCES = {
    "Amar Ujala": ["https://www.amarujala.com/rss/breaking-news.xml", "https://www.amarujala.com/rss/editors-pick.xml"],
    "Hindustan Times": ["https://www.hindustantimes.com/feeds/rss/technology/rssfeed.xml"],
    "Times of India": ["https://timesofindia.indiatimes.com/rssfeedstopstories.cms"],
    "Economic Times": ["https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms"],
}
AI_HINT = re.compile(r"\b(ai|artificial intelligence|machine learning|deep learning|generative ai|genai|llm|large language model|chatgpt|gemini|robotics|agentic)\b", re.I)

@lru_cache(maxsize=16)
def _robots_parser(origin):
    parser = RobotFileParser()
    parser.set_url(origin + "/robots.txt")
    try:
        response = requests.get(parser.url, timeout=8, headers={"User-Agent": "AI-News-Intelligence-Agent/1.0"})
        if response.status_code >= 500:
            parser.disallow_all = True
        elif response.status_code < 400:
            parser.parse(response.text.splitlines())
        else:
            parser.allow_all = True
    except requests.RequestException:
        parser.disallow_all = True
    return parser

def _robots_allows(url):
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    try: return _robots_parser(origin).can_fetch("AI-News-Intelligence-Agent", url)
    except Exception: return False

def _configured_sources():
    """Allow publisher feed URLs to be updated without editing the code."""
    result = {}
    for source, defaults in SOURCES.items():
        key = "RSS_" + re.sub(r"\W+", "_", source).upper()
        raw = os.getenv(key, "")
        result[source] = [u.strip() for u in raw.split(",") if u.strip()] or defaults
    return result

def _date(entry):
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            try: return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
            except (TypeError, ValueError): pass
    return entry.get("published") or entry.get("updated") or None

def _clean_html(value):
    if not value: return ""
    return " ".join(BeautifulSoup(value, "html.parser").get_text(" ", strip=True).split())

def _article_text(url, timeout=12):
    """Extract readable text only from publicly accessible pages; never bypass paywalls."""
    try:
        if not _robots_allows(url): return ""
        response = requests.get(url, timeout=timeout, headers={"User-Agent": "AI-News-Intelligence-Agent/1.0 (RSS reader)"})
        response.raise_for_status()
        if "text/html" not in response.headers.get("Content-Type", "").lower(): return ""
        soup = BeautifulSoup(response.text, "html.parser")
        if soup.find("meta", attrs={"name": re.compile("robots", re.I), "content": re.compile("noarchive|nosnippet", re.I)}): return ""
        for element in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]): element.decompose()
        # RSS metadata remains usable when the publisher blocks or limits page extraction.
        main = soup.find("article") or soup.find("main") or soup.body
        if not main: return ""
        text = " ".join(main.stripped_strings)
        return text[:16000] if len(text) > 300 else ""
    except requests.RequestException:
        return ""

def collect_all(limit_per_feed=80):
    """Return deduplicated feed entries and per-feed errors; article extraction is best effort."""
    articles, errors, seen = [], [], set()
    timeout = int(os.getenv("REQUEST_TIMEOUT", "15"))
    for source, urls in _configured_sources().items():
        for feed_url in urls:
            try:
                response = requests.get(feed_url, timeout=timeout, headers={"User-Agent": "AI-News-Intelligence-Agent/1.0 (RSS reader)"})
                response.raise_for_status()
                feed = feedparser.parse(response.content)
                if not feed.entries: errors.append(f"{source}: feed empty/unavailable ({feed_url})"); continue
                for entry in feed.entries[:limit_per_feed]:
                    url = entry.get("link", "").strip()
                    title = _clean_html(entry.get("title", ""))
                    if not url or not title: continue
                    identity = url.split("#", 1)[0].rstrip("/").lower()
                    if identity in seen: continue
                    seen.add(identity)
                    excerpt = _clean_html(entry.get("summary", "") or entry.get("description", ""))
                    content_parts = entry.get("content", [])
                    feed_content = _clean_html(content_parts[0].get("value", "")) if content_parts else ""
                    # Keep page visits focused on plausible AI stories; feed items are still
                    # recorded for accurate collection totals.
                    body = _article_text(url, timeout=timeout) if AI_HINT.search(title + " " + excerpt) else ""
                    articles.append({"title": title, "source": source, "published_at": _date(entry), "url": url,
                                     "content": body or feed_content or excerpt, "content_status": "page" if body else ("feed excerpt" if feed_content or excerpt else "unavailable")})
            except Exception as exc:
                errors.append(f"{source}: {type(exc).__name__} ({feed_url})")
    return articles, errors
