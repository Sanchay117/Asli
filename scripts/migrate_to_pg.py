"""Copy the local SQLite data (watchlist, snapshots, checks, spend) into Postgres.

Usage: DATABASE_URL=postgres://... python -m scripts.migrate_to_pg
"""
import sqlite3

from asli import db
from asli.db import DB_PATH

src = sqlite3.connect(DB_PATH)
src.row_factory = sqlite3.Row
TABLES = {
    "tracked": "url, store, label, gpu, added",
    "snapshots": "ts, url, store, title, price_inr, mrp_inr, in_stock, availability, seller, page_hash",
    "checks": "ts, url, verdict, result",
    "spend": "ts, provider, model, task, prompt_tokens, completion_tokens, cost_usd, credits, latency_s",
}
with db.conn() as dst:
    for table, cols in TABLES.items():
        rows = src.execute(f"SELECT {cols} FROM {table}").fetchall()
        marks = ",".join("?" * len(cols.split(",")))
        verb = "INSERT OR IGNORE" if table == "tracked" else "INSERT"
        for r in rows:
            dst.execute(f"{verb} INTO {table} ({cols}) VALUES ({marks})", tuple(r))
        print(table, len(rows))
