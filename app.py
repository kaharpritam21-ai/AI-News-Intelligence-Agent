"""Accessible Streamlit dashboard backed by the shared article ledger."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from agents import CATEGORIES, run_workflow
from reporting import counts_for, industry_insights, verified_feed, write_report

ROOT = Path(__file__).resolve().parent
LEDGER_PATH = Path(os.getenv("NEWS_LEDGER_PATH", ROOT / "data" / "article_records.json"))
REPORT_PATH = Path(os.getenv("NEWS_REPORT_PATH", ROOT / "outputs" / "latest_ai_news_report.md"))
LOCAL_TZ = ZoneInfo("Asia/Kolkata")

st.set_page_config(page_title="AI News Intelligence", page_icon="🧭", layout="wide")


def read_ledger() -> dict:
    try:
        return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"meta": {}, "articles": [], "excluded_records": []}


def save_ledger(data: dict) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def date_range(meta: dict) -> tuple[str, str]:
    start = meta.get("coverage_start", "")
    end = meta.get("coverage_end", "")
    if not start or not end:
        today = datetime.now(LOCAL_TZ).date()
        start, end = (today - timedelta(days=6)).isoformat(), today.isoformat()
    return start, end


def matches_filters(article: dict, query: str, publisher: str, category: str, statuses: list[str]) -> bool:
    if statuses and article.get("verification_status") not in statuses:
        return False
    if publisher != "All publishers" and article.get("publisher") != publisher:
        return False
    if category != "All categories" and category not in article.get("categories", []):
        return False
    haystack = " ".join([article.get("headline", ""), article.get("short_description", ""), article.get("summary", "")]).casefold()
    return not query or query.casefold() in haystack


data = read_ledger()
articles = data.get("articles", [])
meta = data.get("meta", {})
coverage_start, coverage_end = date_range(meta)
counts = counts_for(articles)

st.title("AI News Intelligence")
st.caption(f"Publisher coverage · {coverage_start} to {coverage_end} · {meta.get('timezone', 'Asia/Kolkata')} · latest {meta.get('coverage_days', 7)} days")
st.markdown("Research → Verify original pages → Classify → Summarize verified items → Editorial review")

action_left, action_right = st.columns([1, 1])
with action_left:
    refresh = st.button("Refresh latest news", type="primary", use_container_width=True, help="Search configured publisher feeds, verify original pages, then update this shared ledger.")
with action_right:
    report_text = ""
    try:
        report_text = REPORT_PATH.read_text(encoding="utf-8")
    except OSError:
        report_text = ""
    if report_text:
        st.download_button("Download current report", report_text, file_name="ai_news_report.md", mime="text/markdown", use_container_width=True)
    else:
        st.button("Report will be generated on refresh", disabled=True, use_container_width=True)

if refresh:
    with st.spinner("Running the research, verification, classification, summarization, and editorial workflow…"):
        try:
            new_records, errors = run_workflow(days=int(meta.get("coverage_days", 7)))
            by_url = {a.get("url", "").split("#", 1)[0].rstrip("/").lower(): a for a in articles}
            for item in new_records:
                key = item.get("url", "").split("#", 1)[0].rstrip("/").lower()
                old = by_url.get(key)
                if old and old.get("verification_status") == "Verified" and item.get("verification_status") != "Verified":
                    # Preserve a previously verified record if a publisher is temporarily unavailable.
                    item["previous_verification"] = item.get("verification_reason")
                    by_url[key] = {**old, "last_recheck_note": item.get("verification_reason")}
                else:
                    by_url[key] = item
            data["articles"] = list(by_url.values())
            today = datetime.now(LOCAL_TZ).date()
            data.setdefault("meta", {}).update({
                "report_date": today.isoformat(),
                "coverage_days": 7,
                "timezone": "Asia/Kolkata",
                "coverage_start": today.isoformat(),
                "coverage_end": today.isoformat(),
                "last_refreshed": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
            })
            # The rolling period is inclusive of today and the six preceding dates.
            data["meta"]["coverage_start"] = (today - timedelta(days=6)).isoformat()
            save_ledger(data)
            write_report(data, REPORT_PATH)
            count = len(new_records)
            message = f"Refresh complete: checked {count} recent AI candidates; the shared ledger now contains {len(data['articles'])} records."
            if errors:
                message += " Feed issues: " + "; ".join(errors[:5])
            st.session_state["refresh_notice"] = ("success", message)
        except Exception as exc:
            st.session_state["refresh_notice"] = ("error", f"Refresh could not complete: {type(exc).__name__}: {exc}")
    st.rerun()

if "refresh_notice" in st.session_state:
    kind, notice = st.session_state.pop("refresh_notice")
    getattr(st, kind)(notice)

metric_cols = st.columns(4)
metric_cols[0].metric("Discovered", counts["discovered"])
metric_cols[1].metric("Verified", counts["verified"])
metric_cols[2].metric("Needs Review", counts["needs_review"])
metric_cols[3].metric("Unverified", counts["unverified"])

st.divider()
st.subheader("Find articles")
filter_cols = st.columns([1.6, 1, 1.2, 1.2])
with filter_cols[0]:
    query = st.text_input("Search", placeholder="Headline, organization, or topic")
with filter_cols[1]:
    publisher = st.selectbox("Publisher", ["All publishers"] + sorted({a.get("publisher", "Unknown") for a in articles}))
with filter_cols[2]:
    category_values = sorted({c for a in articles for c in a.get("categories", [])})
    category = st.selectbox("Category", ["All categories"] + category_values)
with filter_cols[3]:
    statuses = st.multiselect("Verification status", ["Verified", "Needs Review", "Unverified"], default=["Verified", "Needs Review", "Unverified"])

filtered = [a for a in articles if matches_filters(a, query, publisher, category, statuses)]
verified_rows = [a for a in filtered if a.get("verification_status") == "Verified" and a.get("editorial_disposition", "included") == "included"]
review_rows = [a for a in filtered if a.get("verification_status") != "Verified" or a.get("editorial_disposition") != "included"]

st.header("Verified news")
st.caption("Summaries appear only when the original publisher page is verified. Each summary is checked for 50–70 words.")
if not verified_rows:
    st.info("No verified articles match these filters. Try widening the filters or refresh the publisher feeds.")
for article in verified_rows:
    with st.container(border=True):
        st.markdown(f"#### {article.get('headline', 'Untitled')}")
        st.caption(f"{article.get('publisher', 'Unknown')} · {article.get('publication_date_display') or article.get('publication_date') or 'Publication date unavailable'} · Verification: Verified")
        category_text = ", ".join(article.get("categories", [])) or "Unclassified"
        st.markdown(f"**Categories:** {category_text}")
        st.write(article.get("summary", ""))
        st.caption(f"Summary length: {len(str(article.get('summary', '')).split())} words · Verification evidence: original publisher page, headline, displayed date, and description checked.")
        st.link_button("Open original article", article.get("url", "#"), help="Opens the publisher's original article.")

st.header("Verification ledger")
st.caption("Needs Review and Unverified items are kept separate from the verified feed, with the reason recorded.")
if not review_rows:
    st.success("No unresolved or editorially excluded records match these filters.")
for article in review_rows:
    status = article.get("verification_status", "Unverified")
    with st.container(border=True):
        st.markdown(f"#### {article.get('headline', 'Untitled')}")
        st.caption(f"{article.get('publisher', 'Unknown')} · {article.get('publication_date_display') or article.get('publication_date') or 'Publication date unavailable'} · Verification: {status}")
        st.write(article.get("verification_reason") or article.get("editorial_reason") or "No reason recorded.")
        if article.get("categories"):
            st.markdown("**Potential categories:** " + ", ".join(article["categories"]))
        st.link_button("Open original article for review", article.get("url", "#"))
        evidence = article.get("verification_evidence", {})
        with st.expander("Evidence details"):
            st.json(evidence)

st.header("Verified coverage insights")
insight_rows = verified_feed(articles)
if not insight_rows:
    st.info("Insights will appear when verified articles are available.")
else:
    category_counts = Counter(category_name for row in insight_rows for category_name in row.get("categories", []))
    insight_cols = st.columns([1, 1.4])
    with insight_cols[0]:
        st.subheader("Category breakdown")
        total = max(category_counts.values(), default=1)
        for name, count in category_counts.most_common():
            st.markdown(f"**{name} — {count}**")
            st.progress(count / total, text=f"{count} verified article{'s' if count != 1 else ''}")
    with insight_cols[1]:
        st.subheader("Industry insights")
        for insight in industry_insights(insight_rows):
            st.markdown(f"- {insight}")

with st.expander("About verification"):
    st.write("A Verified badge means the original publisher page was opened and its publisher domain, headline, displayed date, and article text were checked. It confirms what that publisher reported; it does not independently prove every claim. Search snippets and feed metadata alone never qualify an article as Verified.")
    st.write(f"Ledger file: `{LEDGER_PATH}` · Report file: `{REPORT_PATH}`")

