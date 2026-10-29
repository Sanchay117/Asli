"""Exercise the app's Postgres pool step by step to find where it stalls.

Usage: python -m scripts.pool_ping
"""
import time

t = time.time()
print("importing db...", flush=True)
from asli import db  # noqa: E402
print("imported in", round(time.time() - t, 1), "s; pool:", bool(db._pool), flush=True)
t = time.time()
with db.conn() as c:
    print("count tracked:", c.execute("SELECT COUNT(*) FROM tracked").fetchone()[0], round(time.time() - t, 1), "s", flush=True)
