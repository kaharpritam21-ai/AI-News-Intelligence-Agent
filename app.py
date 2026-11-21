"""Streamlit dashboard for the AI News Intelligence Agent."""
from datetime import date, timedelta
from datetime import datetime, timezone
from collections import Counter
import html
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from database import init_db, get_articles, get_existing_urls, stats
from news_collector import collect_all
from news_analyzer import analyze_articles

st.set_page_config(page_title="AI News Intelligence Agent", page_icon="🧠", layout="wide")
init_db()

@st.cache_data(ttl=60)
def load_data():
    return get_articles()

def show_bar_chart(counts):
    """Render a simple accessible bar chart without native dataframe/chart binaries."""
    if not counts:
        st.caption("No data available yet.")
        return
    maximum = max(counts.values()) or 1
    st.markdown('<div style="display:flex;flex-direction:column;gap:0.65rem;padding:0.4rem 0">', unsafe_allow_html=True)
    for label, count in counts.most_common():
        width = max(2, round(100 * count / maximum, 1))
        escaped = html.escape(str(label))
        st.markdown(
            f'<div style="display:grid;grid-template-columns:minmax(120px, 30%) 1fr 2.5rem;gap:.6rem;align-items:center">'
            f'<span style="font-size:.85rem">{escaped}</span>'
            f'<span style="height:.7rem;background:#edf0f5;border-radius:8px;overflow:hidden"><span style="display:block;height:100%;width:{width}%;background:#5266d5;border-radius:8px"></span></span>'
            f'<b style="font-size:.85rem;text-align:right">{int(count)}</b></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

st.title("🧠 AI News Intelligence Agent")
st.caption("A daily view of AI coverage from Amar Ujala, Hindustan Times, Times of India, and Economic Times.")
if "refresh_message" in st.session_state:
    st.info(st.session_state.pop("refresh_message"))
if st.button("🔄 Refresh News", type="primary"):
    with st.spinner("Collecting publisher feeds and analyzing new articles…"):
        try:
            articles, errors = collect_all()
            existing_urls = get_existing_urls()
            unseen = [article for article in articles if article["url"] not in existing_urls]
            analyzed = analyze_articles(unseen)
            from database import upsert_articles
            upsert_articles(analyzed)
            load_data.clear()
            from database import stats
            st.session_state["refresh_message"] = f"Checked {len(articles)} feed items; added {len(analyzed)} new records. Database now contains {stats()['total']} articles, including {stats()['ai']} AI-related." + (f" Feed issues: {'; '.join(errors)}" if errors else "")
        except Exception as exc:
            st.session_state["refresh_message"] = f"Refresh could not complete: {exc}"
        st.rerun()

all_rows = load_data()
summary = stats()
left, right = st.columns(2)
left.metric("Articles collected", summary["total"])
right.metric("AI-related articles", summary["ai"])
if not all_rows:
    st.info("No articles are stored yet. Select **Refresh News** to fetch the configured publisher feeds.")
else:
    source_counts = Counter(row["source"] for row in all_rows)
    category_counts = Counter(row["category"] for row in all_rows if row["is_ai"] == 1 and row["category"])
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Articles by source")
        show_bar_chart(source_counts)
    with c2:
        st.subheader("AI articles by category")
        if category_counts:
            show_bar_chart(category_counts)
        else:
            st.caption("Refresh feeds to populate category analytics.")
    st.subheader("Latest and most important AI news")
    ai = [row for row in all_rows if row["is_ai"] == 1]
    source_options = ["All sources"] + sorted({row["source"] for row in all_rows if row.get("source")})
    category_options = ["All categories"] + sorted({row["category"] for row in ai if row.get("category")})
    f1, f2, f3, f4 = st.columns([1, 1, 1, 1.5])
    with f1: chosen_source = st.selectbox("Source", source_options)
    with f2: chosen_category = st.selectbox("Category", category_options)
    with f3: since = st.date_input("Published since", value=date.today() - timedelta(days=7))
    with f4: query = st.text_input("Search headlines", placeholder="e.g. Gemini, healthcare")
    def published_date(row):
        raw = row.get("published_at")
        if not raw: return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except (TypeError, ValueError): return None
    if chosen_source != "All sources": ai = [row for row in ai if row["source"] == chosen_source]
    if chosen_category != "All categories": ai = [row for row in ai if row["category"] == chosen_category]
    ai = [row for row in ai if published_date(row) is None or published_date(row).date() >= since]
    if query: ai = [row for row in ai if query.casefold() in (row.get("title") or "").casefold()]
    ai.sort(key=lambda row: (int(row.get("importance") or 0), published_date(row) or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    if not ai:
        st.info("No AI articles match these filters.")
    for row in ai:
        with st.container(border=True):
            st.markdown(f"### [{row['title']}]({row['url']})")
            st.caption(f"{row['source']} · {row['published_at'] or 'Date unavailable'} · {row['category']} · Importance {row['importance']}/5")
            if row["summary"]: st.write(row["summary"])
            else: st.write("Article content unavailable; no summary was generated.")
            if row.get("what_happened"): st.markdown(f"**What happened:** {row['what_happened']}")
            if row.get("entities"): st.markdown(f"**Who is involved:** {row['entities']}")
            if row["why_it_matters"]: st.markdown(f"**Why it matters:** {row['why_it_matters']}")
            if row.get("potential_impact"): st.markdown(f"**Potential impact:** {row['potential_impact']}")
            st.markdown(f"[Read the original article]({row['url']})")
    with st.expander("Collection details"):
        st.caption("Stored article records include all feed items; only articles identified as AI-related appear above. Feed/API access and publisher terms apply.")
