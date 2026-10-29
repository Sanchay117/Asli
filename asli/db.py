"""Storage: response cache, spend ledger, watcher snapshots.

SQLite locally; Postgres when DATABASE_URL is set (the hosted app, whose disk is wiped
whenever it sleeps).
"""
import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager

from .config import DATA_DIR

DB_PATH = DATA_DIR / "asli.db"
DATABASE_URL = os.environ.get("DATABASE_URL", "")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY, value TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS spend (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, provider TEXT NOT NULL,
    model TEXT, task TEXT, prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0,
    credits REAL DEFAULT 0, latency_s REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tracked (
    url TEXT PRIMARY KEY, store TEXT, label TEXT, gpu TEXT, added REAL
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, url TEXT NOT NULL, store TEXT,
    title TEXT, price_inr INTEGER, mrp_inr INTEGER, in_stock INTEGER,
    availability TEXT, seller TEXT, page_hash TEXT
);
CREATE INDEX IF NOT EXISTS snapshots_url ON snapshots(url, ts);
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, url TEXT, verdict TEXT, result TEXT
);
"""


class _Row(dict):
    """Postgres row that can be read by name or by position, like sqlite3.Row."""

    def __init__(self, cols, vals):
        super().__init__(zip(cols, vals))
        self._vals = vals

    def __getitem__(self, k):
        return self._vals[k] if isinstance(k, int) else super().__getitem__(k)


def _row_factory(cursor):
    cols = [c.name for c in cursor.description] if cursor.description else []
    return lambda values: _Row(cols, values)


def _to_pg(sql):
    """Translate the small SQLite dialect used in this app to Postgres."""
    sql = sql.replace("%", "%%").replace("?", "%s")
    if sql.lstrip().upper().startswith("INSERT OR IGNORE"):
        sql = re.sub(r"(?i)INSERT OR IGNORE", "INSERT", sql, count=1) + " ON CONFLICT DO NOTHING"
    sql = re.sub(r"(?i)\bINTEGER PRIMARY KEY\b", "BIGSERIAL PRIMARY KEY", sql)
    return re.sub(r"(?i)\bREAL\b", "DOUBLE PRECISION", sql)


class _PgConn:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=()):
        return self.raw.execute(_to_pg(sql), params)

    def executescript(self, script):
        for stmt in script.split(";"):
            if stmt.strip():
                self.execute(stmt)


_pool = None
if DATABASE_URL:
    from psycopg_pool import ConnectionPool
    _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=8,
                           kwargs={"row_factory": _row_factory, "autocommit": True})


@contextmanager
def conn():
    if _pool:
        with _pool.connection() as raw:
            yield _PgConn(raw)
        return
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def cache_get(key, ttl_s):
    with conn() as c:
        row = c.execute("SELECT value, created FROM cache WHERE key=?", (key,)).fetchone()
    if row and time.time() - row["created"] < ttl_s:
        return json.loads(row["value"])
    return None


def cache_put(key, value):
    with conn() as c:
        c.execute("DELETE FROM cache WHERE key=?", (key,))
        c.execute("INSERT INTO cache VALUES (?,?,?)", (key, json.dumps(value), time.time()))


def record_spend(**row):
    row.setdefault("ts", time.time())
    cols = ",".join(row)
    with conn() as c:
        c.execute(f"INSERT INTO spend ({cols}) VALUES ({','.join('?' * len(row))})",
                  tuple(row.values()))


def month_start():
    t = time.gmtime()
    return time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))


def spend_totals():
    with conn() as c:
        total = c.execute("SELECT COALESCE(SUM(cost_usd),0) FROM spend").fetchone()[0]
        month = c.execute("SELECT COALESCE(SUM(cost_usd),0) FROM spend WHERE ts>=?",
                          (month_start(),)).fetchone()[0]
        credits = c.execute(
            "SELECT COALESCE(SUM(credits),0) FROM spend WHERE provider='tavily' AND ts>=?",
            (month_start(),)).fetchone()[0]
        by_model = [dict(r) for r in c.execute(
            "SELECT model, task, COUNT(*) calls, SUM(prompt_tokens) prompt_tokens, "
            "SUM(completion_tokens) completion_tokens, SUM(cost_usd) cost_usd, "
            "AVG(latency_s) latency_s FROM spend WHERE provider='nebius' "
            "GROUP BY model, task ORDER BY cost_usd DESC")]
    return {"total_usd": total, "month_usd": month, "tavily_credits_month": credits,
            "by_model": by_model}


init()
