# AI News Intelligence

A multi-agent style research workflow and interactive Streamlit dashboard for recent AI coverage from Times of India, The Economic Times, Hindustan Times, and Amar Ujala. The project prioritizes traceable source pages over a fixed number of articles.

## What it does

The named agents run in sequence over one shared article record:

```text
Publisher RSS feeds
       ↓
Research Agent → recent AI candidates, exact headline/source/date/original URL
       ↓
Verification Agent → opens original publisher page, checks domain/headline/visible date/text support
       ↓
Classification Agent → Generative AI, Machine Learning, Robotics, AI Business,
                       AI Research, AI Safety & Governance, AI in Society
       ↓
Summarization Agent → 50–70 simple-English words for Verified articles only
       ↓
Editorial Agent → remove duplicate stories and irrelevant articles
       ↓
Shared JSON ledger → Streamlit dashboard + Markdown report + verification ledger
```

The workflow is implemented as sequential specialist agents, not parallel calls. Full article text is used transiently for checks and summaries; the shared ledger stores metadata, evidence notes, and summaries, not full article bodies.

## Dashboard

- Rolling latest-seven-days coverage in Asia/Kolkata time.
- Discovered, Verified, Needs Review, and Unverified totals.
- Verified article cards with headline, publisher, page-displayed date, categories, word-counted summary, verification badge, and original-source link.
- Search and publisher, category, and verification-status filters.
- Category breakdown and industry insights derived only from Verified records.
- A separate verification ledger with reasons and evidence for unresolved or editorially excluded records.
- Refresh action and a downloadable Markdown report generated from the same JSON ledger.

## Run on Windows

1. Install Python 3.10 or newer.
2. Open PowerShell in this folder and prepare the environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. Optional: copy `.env.example` to `.env` and add an OpenAI API key for abstractive summaries. The project still runs without a key using a cautious, source-grounded fallback.
4. Start the dashboard:

   ```powershell
   streamlit run app.py
   ```

5. Open the local address printed by Streamlit. Use **Refresh latest news** to run the live workflow.

## Current reviewed snapshot

The repository includes a real, source-checked snapshot in `data/article_records.json`, reviewed on November 22, 2026. It covers November 16–22, 2026 and starts with five verified article records from the four publishers. These are not fabricated sample stories. The refresh action rechecks pages; pages that cannot be opened, have conflicting dates, or do not substantiate descriptions remain in Needs Review or Unverified status and are excluded from the Verified feed.

`outputs/latest_ai_news_report.md` is rendered from that same snapshot. The dashboard also reads that JSON file, so article totals and report totals share one source of truth.

## Verification policy and limitations

- The original publisher page is the primary evidence. Search snippets and RSS text alone never earn Verified status.
- The verifier checks the publisher domain, page headline, visible page date, and description terms in the article text. A publisher page supports what that publisher reported; it does not independently prove every reported claim.
- The displayed date label is preserved, including “Last Updated” where that is what the page shows. The seven-day window uses the visible date in Asia/Kolkata time.
- If a page is blocked, the date is missing or conflicts, or the article text does not support the description, the record remains Needs Review. A host mismatch or headline mismatch is Unverified.
- The summarizer only runs on Verified records and enforces 50–70 whitespace-separated words. If a grounded summary cannot be produced, the record is moved to Needs Review.
- Publisher feeds and terms can change. Respect each publisher's RSS, robots, copyright, and reuse terms. The app does not bypass access controls or paywalls.

## Files

- `app.py` — responsive interactive Streamlit dashboard.
- `agents.py` — Research, Verification, Classification, Summarization, and Editorial agents.
- `news_collector.py` — publisher RSS discovery and permitted page extraction.
- `reporting.py` — report generation and shared status counts.
- `data/article_records.json` — common article, evidence, category, and summary ledger.
- `outputs/latest_ai_news_report.md` — report generated from the ledger.
- `.env.example` — optional configuration template.

## Configuration

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Optional API key for article summaries; keep it only in `.env`. |
| `OPENAI_MODEL` | Optional model name; defaults to `gpt-4o-mini`. |
| `RSS_AMAR_UJALA`, `RSS_HINDUSTAN_TIMES`, `RSS_TIMES_OF_INDIA`, `RSS_ECONOMIC_TIMES` | Optional comma-separated RSS feed overrides. |
| `NEWS_LEDGER_PATH` | Optional override for the JSON article ledger. |
| `NEWS_REPORT_PATH` | Optional override for the generated Markdown report. |
| `REQUEST_TIMEOUT` | HTTP timeout in seconds for publisher pages and feeds. |

