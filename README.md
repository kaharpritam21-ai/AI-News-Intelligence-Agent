# AI News Intelligence Agent

A beginner-friendly Streamlit application that reads publisher RSS feeds, checks accessible article pages where permitted, identifies AI-related articles, summarizes available reporting, and stores results in SQLite. It is one multi-step agent with separate Python modules for collection, analysis, storage, and display. The dashboard uses built-in Python data structures for filtering and chart preparation to keep its runtime lightweight.

## Architecture

```text
Publisher RSS feeds → news_collector.py → news_analyzer.py → database.py (SQLite)
                                                                     ↓
                                                        app.py (Streamlit dashboard)
```

The optional OpenAI API analyzes relevance, categories, summaries, and importance. Without an API key, keyword rules run locally; they do not claim a verified 3–5 sentence summary where the accessible source text is missing. Feed excerpts and article pages may be incomplete. The dashboard links to publisher originals.

## Setup (Windows PowerShell)

1. Install Python 3.10 or newer.
2. Open PowerShell in this folder and create an environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. Copy the sample settings and optionally add your API key and model:

   ```powershell
   Copy-Item .env.example .env
   ```

   Edit `.env` in a text editor. `.env` is ignored by git (do not commit real keys).
4. Start the dashboard:

   ```powershell
   streamlit run app.py
   ```

5. Select **Refresh News** to collect and analyze live feed items. The SQLite database is created as `news.db` on first use.

## Feeds and access

Default feeds are configured in `news_collector.py`; URLs can be overridden through the `RSS_*` settings in `.env`. The Times Internet publishers' RSS terms limit use to personal, non-commercial use and prohibit further publication; use this app only within the permissions applicable to you. Publisher feed URLs and terms can change, so confirm the current terms before use. Collection handles unavailable feeds and network failures without fabricating article records. Page extraction is best effort; it does not sign in, evade blocks, or bypass paywalls. Article text is processed transiently and is not written to SQLite. If an article cannot be accessed, the agent uses only available RSS metadata/text and explicitly marks insufficient content in its summary.

The dashboard's total counts reflect stored AI-related articles and the records successfully analyzed; it does not retain rejected irrelevant entries. Remove `news.db` to clear local article history.

## Configuration

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Optional key for LLM classification and analysis |
| `OPENAI_MODEL` | Model name; defaults to `gpt-4o-mini` |
| `RSS_AMAR_UJALA`, `RSS_HINDUSTAN_TIMES`, `RSS_TIMES_OF_INDIA`, `RSS_ECONOMIC_TIMES` | Optional comma-separated feed URL overrides |
| `NEWS_DB_PATH` | SQLite file path (defaults to `news.db`) |
| `REQUEST_TIMEOUT` | HTTP timeout in seconds |

## Notes

- Article text is processed for the personal news dashboard; comply with each publisher's terms and applicable law.
- Summary fields are based only on retrieved feed/article text. Publisher links remain the canonical source.
- Ranking combines recency in the dashboard ordering with a 1–5 importance score from the analyzer.
