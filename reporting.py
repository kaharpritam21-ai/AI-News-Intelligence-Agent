"""Render the downloadable report from the dashboard's shared article ledger."""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

STATUSES = ("Verified", "Needs Review", "Unverified")


def counts_for(articles: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "discovered": len(articles),
        "verified": sum(a.get("verification_status") == "Verified" for a in articles),
        "needs_review": sum(a.get("verification_status") == "Needs Review" for a in articles),
        "unverified": sum(a.get("verification_status") == "Unverified" for a in articles),
    }


def verified_feed(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        a for a in articles
        if a.get("verification_status") == "Verified"
        and a.get("editorial_disposition", "included") == "included"
        and a.get("categories")
        and 50 <= len(str(a.get("summary", "")).split()) <= 70
    ]


def industry_insights(articles: list[dict[str, Any]]) -> list[str]:
    rows = verified_feed(articles)
    joined = " ".join((a.get("headline", "") + " " + a.get("short_description", "")).lower() for a in rows)
    insights: list[str] = []
    if "highway" in joined or "cctv" in joined:
        insights.append("AI deployment is reaching public infrastructure: verified coverage describes highway inspection and surveillance uses. Potential industry demand includes analytics, sensors, and system integration; results remain to be measured.")
    if "iit" in joined or "research" in joined:
        insights.append("University partnerships and research facilities are a visible route for building AI capability, connecting research, infrastructure, and potential startup development.")
    if "student" in joined or "training" in joined or "iti" in joined:
        insights.append("AI education and vocational training are part of the adoption picture; practical skills may help prepare workers to use and support AI systems.")
    if not insights:
        insights.append("The verified articles do not yet support a broader cross-industry pattern.")
    return insights


def build_report(data: dict[str, Any]) -> str:
    meta = data.get("meta", {})
    articles = data.get("articles", [])
    counts = counts_for(articles)
    verified = verified_feed(articles)
    unresolved = [a for a in articles if a.get("verification_status") != "Verified" or a.get("editorial_disposition") != "included"]
    start = meta.get("coverage_start") or (date.fromisoformat(meta.get("report_date", date.today().isoformat())) - timedelta(days=6)).isoformat()
    end = meta.get("coverage_end") or meta.get("report_date", date.today().isoformat())
    start_display = date.fromisoformat(start).strftime("%b %d, %Y")
    end_display = date.fromisoformat(end).strftime("%b %d, %Y")

    lines = [
        "# AI News Intelligence Report",
        f"**Report date:** {meta.get('report_date', date.today().isoformat())}  ",
        f"**Coverage:** {start_display}–{end_display} ({meta.get('timezone', 'Asia/Kolkata')}; latest {meta.get('coverage_days', 7)} days)",
        "",
        "## Executive Summary",
        f"The research workflow discovered **{counts['discovered']}** AI-related candidate articles from the four configured publishers. **{counts['verified']}** are verified against original publisher pages, **{counts['needs_review']}** need review, and **{counts['unverified']}** are unverified. Only verified, non-duplicate articles with a 50–70 word summary appear in the news sections below.",
        "",
        "## Category-Wise Verified News",
    ]
    by_category: dict[str, list[dict[str, Any]]] = {}
    for article in verified:
        # Use the first evidence-backed label as the report's primary section.
        # All additional labels remain visible in article metadata and dashboard filters.
        primary = (article.get("categories") or ["AI in Society"])[0]
        by_category.setdefault(primary, []).append(article)
    if not by_category:
        lines.extend(["No verified articles are available for this coverage period.", ""])
    for category in sorted(by_category):
        lines.extend([f"### {category}", ""])
        seen: set[str] = set()
        for article in by_category[category]:
            if article["id"] in seen:
                continue
            seen.add(article["id"])
            lines.extend([
                f"#### [{article['headline']}]({article['url']})",
                f"**{article['publisher']} · {article.get('publication_date_display') or article.get('publication_date') or 'Date unavailable'} · Verified**",
                f"**Categories:** {', '.join(article.get('categories', []))}",
                "",
                article["summary"],
                "",
            ])
    lines.extend(["## Key Industry Insights", ""])
    lines.extend(f"- {insight}" for insight in industry_insights(verified))
    lines.extend([
        "",
        "## Verification Ledger",
        f"- Discovered: {counts['discovered']}",
        f"- Verified: {counts['verified']}",
        f"- Needs Review: {counts['needs_review']}",
        f"- Unverified: {counts['unverified']}",
        "",
    ])
    if unresolved:
        for item in unresolved:
            lines.extend([
                f"- **{item.get('verification_status', 'Unverified')} — {item.get('headline', 'Untitled')}** ({item.get('publisher', 'Unknown')})",
                f"  - Reason: {item.get('verification_reason') or item.get('editorial_reason') or 'No reason recorded.'}",
                f"  - [Original article]({item.get('url', '')})",
            ])
    else:
        lines.append("No unresolved verification or editorial exclusions in the current records.")
    lines.extend([
        "",
        "## Method and Limitations",
        "The verification status confirms that the named publisher's original page was opened and that its headline, displayed date, and article text support the recorded description. It does not independently prove every claim made by the publisher. Search snippets and RSS metadata alone are not enough to mark an article Verified.",
        "",
    ])
    return "\n".join(lines)


def write_report(data: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_report(data), encoding="utf-8")
    return target

