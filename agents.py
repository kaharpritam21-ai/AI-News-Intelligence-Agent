"""Sequential research, verification, classification, summary, and editorial agents.

Each role receives and enriches the same article record. Full article text is
kept in memory only and is never written to the local article ledger.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
import hashlib
import html
import json
import os
import re
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from openai import OpenAI

from news_collector import collect_all, _robots_allows

LOCAL_TZ = ZoneInfo("Asia/Kolkata")
SOURCE_HOSTS = {
    "Times of India": {"timesofindia.indiatimes.com"},
    "The Economic Times": {"economictimes.indiatimes.com"},
    "Economic Times": {"economictimes.indiatimes.com"},
    "The Economic Times": {"economictimes.indiatimes.com"},
    "Hindustan Times": {"hindustantimes.com"},
    "Amar Ujala": {"amarujala.com"},
}
CATEGORIES = [
    "Generative AI", "Machine Learning", "Robotics", "AI Business",
    "AI Research", "AI Safety & Governance", "AI in Society",
]
AI_HINT = re.compile(
    r"\b(ai|artificial intelligence|machine learning|deep learning|generative ai|genai|"
    r"llm|large language model|chatgpt|gemini|robotics|agentic ai)\b", re.I,
)
STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "over", "under",
    "will", "would", "could", "should", "about", "after", "before", "while", "where",
    "when", "what", "which", "their", "them", "they", "its", "are", "was", "were",
    "has", "have", "had", "been", "being", "article", "reports", "report", "says",
    "said", "according", "more", "than", "also", "such", "some", "other", "into",
}


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value).strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(raw)
            except (TypeError, ValueError, OverflowError):
                try:
                    parsed = date_parser.parse(raw, fuzzy=False)
                except (TypeError, ValueError, OverflowError):
                    return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(LOCAL_TZ)
    return parsed.date()


def _normal(value: str) -> str:
    value = html.unescape(value or "").lower()
    return re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).strip()


def _safe_excerpt(value: str, limit: int = 900) -> str:
    clean = " ".join(BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True).split())
    return clean[:limit]


def _article_id(url: str) -> str:
    return hashlib.sha256(url.split("#", 1)[0].rstrip("/").encode("utf-8")).hexdigest()[:16]


def _host_matches(source: str, host: str) -> bool:
    hosts = SOURCE_HOSTS.get(source, set())
    return any(host == expected or host.endswith("." + expected) for expected in hosts)


def _meaningful_tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", _normal(value))
        if (len(token) >= 3 and token not in STOP_WORDS) or token.isdigit()
    }


def _displayed_date(text: str, soup: BeautifulSoup) -> str | None:
    # Prefer visible date text associated with article metadata, then the first
    # visible date immediately following the page headline.
    for node in soup.select("article time, main time, time"):
        value = " ".join(node.get_text(" ", strip=True).split())
        if value and _parse_date(value):
            return value
    article_text = text
    heading = soup.find("h1")
    if heading:
        headline = " ".join(heading.get_text(" ", strip=True).split())
        idx = article_text.find(headline)
        if idx >= 0:
            article_text = article_text[idx + len(headline):idx + len(headline) + 1600]
    patterns = [
        r"(?:Published(?:\s+on)?|Last\s+Updated|Updated(?:\s+on)?)\s*:?\s*"
        r"(?:[A-Za-z]{3,9},?\s+)?\d{1,2}[\s/-]+[A-Za-z]{3,9}[\s/-]+\d{4}"
        r"(?:,?\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?\s*(?:IST|UTC)?)?",
        r"(?:[A-Za-z]{3,9},?\s+)?\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}"
        r"(?:,?\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?\s*(?:IST|UTC)?)?",
        r"[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}(?:,?\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?\s*(?:IST|UTC)?)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, article_text, re.I)
        if match:
            candidate = " ".join(match.group(0).split())
            # Drop a field label from the display value but keep the exact date/time.
            candidate = re.sub(r"^(?:Published(?:\s+on)?|Last\s+Updated|Updated(?:\s+on)?)\s*:?\s*", "", candidate, flags=re.I)
            if _parse_date(candidate):
                return candidate
    return None


class ResearchAgent:
    """Collect publisher RSS records and apply the rolling seven-day window."""

    def __init__(self, days: int = 7, today: date | None = None):
        self.days = days
        self.today = today or datetime.now(LOCAL_TZ).date()

    def run(self) -> tuple[list[dict[str, Any]], list[str]]:
        raw_articles, errors = collect_all()
        first_day = self.today - timedelta(days=self.days - 1)
        found: list[dict[str, Any]] = []
        for item in raw_articles:
            title = str(item.get("title") or "").strip()
            excerpt = _safe_excerpt(item.get("content") or item.get("summary") or "")
            if not title or not AI_HINT.search(title + " " + excerpt):
                continue
            pub_day = _parse_date(item.get("published_at"))
            if pub_day and not (first_day <= pub_day <= self.today):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            publisher = item.get("source", "Unknown")
            if publisher == "Economic Times":
                publisher = "The Economic Times"
            found.append({
                "id": _article_id(url),
                "headline": title,
                "publisher": publisher,
                "publication_date": pub_day.isoformat() if pub_day else None,
                "publication_date_display": item.get("published_at"),
                "url": url,
                "short_description": excerpt,
                "verification_status": "Needs Review",
                "verification_reason": "Not yet checked against the original publisher page.",
                "verification_evidence": {},
                "categories": [],
                "category_evidence": {},
                "summary": "",
                "summary_word_count": 0,
                "editorial_disposition": "candidate",
                "discovery_source": "publisher RSS",
                "_article_text": str(item.get("content") or ""),
            })
        return found, errors


class VerificationAgent:
    """Open every original URL and compare page identity, visible date and description."""

    def __init__(self, timeout: int | None = None):
        self.timeout = timeout or int(os.getenv("REQUEST_TIMEOUT", "15"))
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "AI-News-Intelligence-Agent/2.0 (source verifier)"})

    def verify(self, item: dict[str, Any]) -> dict[str, Any]:
        url = item.get("url", "")
        initial_host = urlparse(url).hostname or ""
        evidence: dict[str, Any] = {"url_host": initial_host, "checked_at": datetime.now(LOCAL_TZ).isoformat(timespec="seconds")}
        reasons: list[str] = []
        if not _host_matches(item.get("publisher", ""), initial_host):
            item.update(verification_status="Unverified", verification_reason="URL host does not match the named publisher.", verification_evidence=evidence)
            return item
        if not _robots_allows(url):
            item.update(verification_status="Needs Review", verification_reason="Publisher robots policy or network response prevented direct page inspection.", verification_evidence=evidence)
            return item
        try:
            response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            evidence.update({"http_status": response.status_code, "final_url": response.url})
            response.raise_for_status()
            final_host = urlparse(response.url).hostname or ""
            evidence["final_host"] = final_host
            if not _host_matches(item.get("publisher", ""), final_host):
                item.update(verification_status="Unverified", verification_reason="The original URL redirected outside the named publisher domain.", verification_evidence=evidence)
                return item
            if "html" not in response.headers.get("Content-Type", "").lower():
                item.update(verification_status="Needs Review", verification_reason="The original URL did not return an HTML article page.", verification_evidence=evidence)
                return item
            soup = BeautifulSoup(response.text, "html.parser")
            h1 = soup.find("h1")
            page_headline = " ".join((h1 or soup.title or soup).get_text(" ", strip=True).split()) if (h1 or soup.title) else ""
            evidence["page_headline"] = page_headline
            headline_score = SequenceMatcher(None, _normal(item.get("headline", "")), _normal(page_headline)).ratio()
            evidence["headline_match_score"] = round(headline_score, 3)
            if headline_score < 0.72:
                item.update(verification_status="Unverified", verification_reason="The original page headline does not match the discovered headline closely enough.", verification_evidence=evidence)
                return item
            main = soup.find("article") or soup.find("main") or soup.body or soup
            for node in main.select("script,style,nav,footer,header,aside,noscript"):
                node.decompose()
            visible_text = "\n".join(main.stripped_strings)
            evidence["page_text_characters"] = len(visible_text)
            shown_date = _displayed_date(visible_text, soup)
            evidence["displayed_date"] = shown_date
            page_day = _parse_date(shown_date)
            expected_day = _parse_date(item.get("publication_date") or item.get("publication_date_display"))
            evidence["page_date"] = page_day.isoformat() if page_day else None
            evidence["discovery_date"] = expected_day.isoformat() if expected_day else None
            date_ok = bool(page_day and expected_day and page_day == expected_day)
            evidence["publication_date_match"] = date_ok
            description_tokens = _meaningful_tokens(item.get("short_description", ""))
            page_tokens = _meaningful_tokens(visible_text)
            matched = sorted(description_tokens & page_tokens)
            coverage = len(matched) / max(len(description_tokens), 1)
            evidence["description_token_coverage"] = round(coverage, 3)
            evidence["supporting_terms"] = matched[:30]
            if len(visible_text) < 300:
                reasons.append("The accessible page text is too short to substantiate the description.")
            if not shown_date or not page_day:
                reasons.append("A publication date could not be read from visible article-page text.")
            elif not date_ok:
                reasons.append("The displayed page date does not match the discovery date.")
            if coverage < 0.28:
                reasons.append("The article text does not provide enough text evidence for the recorded description.")
            item["publication_date_display"] = shown_date
            item["publication_date"] = page_day.isoformat() if page_day else item.get("publication_date")
            evidence["evidence_note"] = "Original publisher page opened; headline, visible date and description terms compared against the page text."
            item["verification_evidence"] = evidence
            if reasons:
                item["verification_status"] = "Needs Review"
                item["verification_reason"] = " ".join(reasons)
            else:
                item["verification_status"] = "Verified"
                item["verification_reason"] = "Original publisher page, headline, visible publication date, and description were checked and matched. This verifies the publisher report, not every underlying claim."
            item["_article_text"] = visible_text[:18000]
            return item
        except requests.RequestException as exc:
            evidence["error_type"] = type(exc).__name__
            item.update(verification_status="Needs Review", verification_reason="The original publisher page could not be fetched; a search result or feed snippet is not sufficient verification.", verification_evidence=evidence)
            return item


class ClassificationAgent:
    """Assign only categories with clear textual evidence; retain reasons."""

    RULES = {
        "Generative AI": ["generative ai", "genai", "text-to-image", "image generation", "ai-generated", "language model", "chatgpt"],
        "Machine Learning": ["machine learning", "trained model", "training data", "neural network"],
        "Robotics": ["robot", "robotics", "autonomous robot", "robotic"],
        "AI Business": ["funding", "investment", "company", "business", "enterprise", "commercial", "contract", "project", "industry partner", "deployment"],
        "AI Research": ["research", "study", "scientific", "institute", "university", "research park", "centre of excellence", "center of excellence"],
        "AI Safety & Governance": ["privacy", "surveillance", "facial recognition", "regulation", "governance", "safety", "audit", "consent", "risk"],
        "AI in Society": ["student", "school", "education", "training", "public", "police", "highway", "traffic", "workforce", "community"],
    }

    def classify(self, item: dict[str, Any]) -> dict[str, Any]:
        text = " ".join([item.get("headline", ""), item.get("short_description", ""), item.get("_article_text", "")]).lower()
        categories: list[str] = []
        evidence: dict[str, list[str]] = {}
        for category, phrases in self.RULES.items():
            matches = [phrase for phrase in phrases if phrase in text]
            if matches:
                categories.append(category)
                evidence[category] = matches[:5]
        if not categories and AI_HINT.search(text):
            # AI is relevant but the available evidence does not justify a narrow tag.
            categories = ["AI in Society"]
            evidence["AI in Society"] = ["AI relevance present; narrow category evidence unavailable"]
        item["categories"] = categories
        item["category_evidence"] = evidence
        item["is_ai"] = bool(AI_HINT.search(text) and categories)
        if not item["is_ai"]:
            item["editorial_disposition"] = "excluded_irrelevant"
            item["editorial_reason"] = "The article text is not meaningfully about artificial intelligence."
        return item


class SummarizationAgent:
    """Summarize verified pages only; enforce a 50–70 word output."""

    def __init__(self):
        key = os.getenv("OPENAI_API_KEY", "").strip()
        self.client = OpenAI(api_key=key, timeout=35, max_retries=1) if key else None
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    @staticmethod
    def _fallback(item: dict[str, Any]) -> str:
        headline = item.get("headline", "")
        publisher = item.get("publisher", "the publisher")
        description = item.get("short_description", "").strip()
        if not description:
            return ""
        base = f"{publisher} reports that {description}"
        if not base.endswith((".", "!", "?")):
            base += "."
        tail = (
            " This matters because it shows where AI is being applied or developed. "
            "A possible industry effect is greater demand for related skills, research, or infrastructure. "
            "That effect is an inference; the article does not establish a measured outcome."
        )
        summary = (base + tail).strip()
        words = summary.split()
        if len(words) < 50:
            summary = f"{summary} The report's headline is: {headline}."
        if len(summary.split()) > 70:
            # Keep complete sentences, dropping the final generic sentence first.
            sentences = re.split(r"(?<=[.!?])\s+", summary)
            while sentences and len(" ".join(sentences).split()) > 70:
                sentences.pop()
            summary = " ".join(sentences)
        return summary if 50 <= len(summary.split()) <= 70 else ""

    def summarize(self, item: dict[str, Any]) -> dict[str, Any]:
        if item.get("verification_status") != "Verified":
            item["summary"] = ""
            item["summary_word_count"] = 0
            return item
        content = item.get("_article_text", "")
        summary = ""
        if self.client and len(content) >= 400:
            prompt = (
                "Summarize this verified publisher article in simple English, exactly 50–70 whitespace-separated words. "
                "State what happened, why it matters, and a possible technology-industry impact. Attribute claims to the publisher; "
                "label any impact as a possibility, not a proven outcome. Use only facts in the article. Return only the summary.\n\n"
                f"Publisher: {item.get('publisher')}\nHeadline: {item.get('headline')}\nArticle text:\n{content[:14000]}"
            )
            try:
                response = self.client.chat.completions.create(
                    model=self.model, temperature=0,
                    messages=[{"role": "system", "content": "You are a careful news editor. Do not invent facts."}, {"role": "user", "content": prompt}],
                )
                candidate = response.choices[0].message.content.strip()
                if 50 <= len(candidate.split()) <= 70:
                    summary = candidate
            except Exception:
                summary = ""
        if not summary:
            summary = self._fallback(item)
        item["summary"] = summary
        item["summary_word_count"] = len(summary.split()) if summary else 0
        if not summary:
            item["verification_status"] = "Needs Review"
            item["verification_reason"] = (item.get("verification_reason", "") + " The description was too limited to produce a 50–70 word grounded summary.").strip()
        return item


class EditorialAgent:
    """Deduplicate and create a single consistent record set for every output."""

    def edit(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        kept: list[dict[str, Any]] = []
        for item in sorted(records, key=lambda x: (x.get("publication_date") or "", x.get("headline", "")), reverse=True):
            normalized_url = item.get("url", "").split("#", 1)[0].rstrip("/").lower()
            normalized_headline = _normal(item.get("headline", ""))
            duplicate = next((old for old in kept if normalized_url == old.get("url", "").split("#", 1)[0].rstrip("/").lower()
                              or SequenceMatcher(None, normalized_headline, _normal(old.get("headline", ""))).ratio() >= 0.9), None)
            if duplicate:
                item["editorial_disposition"] = "excluded_duplicate"
                item["duplicate_of"] = duplicate.get("id")
                item["editorial_reason"] = f"Duplicate of {duplicate.get('headline')}"
                kept.append(item)
                continue
            if item.get("editorial_disposition", "candidate") == "candidate":
                item["editorial_disposition"] = "included" if item.get("is_ai") else "excluded_irrelevant"
            kept.append(item)
        return kept


def run_workflow(days: int = 7, today: date | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Run each named agent sequentially over one shared record collection."""
    discovered, errors = ResearchAgent(days=days, today=today).run()
    verifier = VerificationAgent()
    classifier = ClassificationAgent()
    summarizer = SummarizationAgent()
    processed = []
    for item in discovered:
        item = verifier.verify(item)
        item = classifier.classify(item)
        item = summarizer.summarize(item)
        item.pop("_article_text", None)
        processed.append(item)
    return EditorialAgent().edit(processed), errors

