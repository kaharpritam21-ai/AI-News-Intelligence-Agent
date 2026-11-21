"""SQLite persistence and headline/URL duplicate detection."""
import hashlib
import os
import re
from difflib import SequenceMatcher
from contextlib import closing
import sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("NEWS_DB_PATH", "news.db"))

def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn

def _normalize_title(title):
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()

def init_db():
    with closing(_connect()) as conn, conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY, url TEXT NOT NULL UNIQUE, title TEXT NOT NULL, title_hash TEXT NOT NULL,
            source TEXT NOT NULL, published_at TEXT, content TEXT, content_status TEXT, is_ai INTEGER NOT NULL,
            category TEXT, summary TEXT, what_happened TEXT, entities TEXT, why_it_matters TEXT, potential_impact TEXT,
            importance INTEGER NOT NULL DEFAULT 0, collected_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(articles)")}
        for column in ("what_happened", "entities", "potential_impact"):
            if column not in existing: conn.execute(f"ALTER TABLE articles ADD COLUMN {column} TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_date ON articles(published_at)")

def upsert_articles(articles):
    init_db(); saved = 0
    with closing(_connect()) as conn, conn:
        for a in articles:
            title_hash = hashlib.sha256(_normalize_title(a["title"]).encode()).hexdigest()
            # Similar headline from another publisher: keep first record to avoid duplicate stories.
            normalized = _normalize_title(a["title"])
            similar = conn.execute("SELECT id,title FROM articles WHERE title_hash=?", (title_hash,)).fetchone()
            if not similar:
                for candidate in conn.execute("SELECT id,title FROM articles WHERE published_at IS ? OR substr(published_at,1,10)=substr(?,1,10)", (a.get("published_at"), a.get("published_at"))).fetchall():
                    if SequenceMatcher(None, normalized, _normalize_title(candidate["title"])).ratio() >= 0.92:
                        similar = candidate; break
            if similar: continue
            conn.execute("""INSERT INTO articles(url,title,title_hash,source,published_at,content,content_status,is_ai,category,summary,what_happened,entities,why_it_matters,potential_impact,importance)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET title=excluded.title, published_at=excluded.published_at,
                content=excluded.content, content_status=excluded.content_status, is_ai=excluded.is_ai, category=excluded.category,
                summary=excluded.summary, what_happened=excluded.what_happened, entities=excluded.entities,
                why_it_matters=excluded.why_it_matters, potential_impact=excluded.potential_impact, importance=excluded.importance""",
                # Article body is used transiently for analysis and not retained in SQLite.
                (a["url"], a["title"], title_hash, a["source"], a.get("published_at"), None, a.get("content_status"), int(a.get("is_ai", True)), a.get("category"), a.get("summary"), a.get("what_happened"), a.get("entities"), a.get("why_it_matters"), a.get("potential_impact"), int(a.get("importance", 0))))
            saved += 1
    return saved

def get_articles():
    init_db()
    with closing(_connect()) as conn: return [dict(r) for r in conn.execute("SELECT * FROM articles ORDER BY published_at DESC")]

def get_existing_urls():
    init_db()
    with closing(_connect()) as conn: return {r[0] for r in conn.execute("SELECT url FROM articles")}

def stats():
    init_db()
    with closing(_connect()) as conn:
        row = conn.execute("SELECT COUNT(*) total, COALESCE(SUM(is_ai),0) ai FROM articles").fetchone()
        return {"total": row["total"], "ai": row["ai"]}
