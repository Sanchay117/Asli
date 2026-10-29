"""Connect to DATABASE_URL directly with a timeout and report what happens (no secrets printed).

Usage: python -m scripts.pg_ping
"""
import os
import time
from urllib.parse import urlparse

import psycopg

from asli import config  # noqa: F401  loads .env

url = os.environ["DATABASE_URL"]
u = urlparse(url)
print("scheme", u.scheme, "host", u.hostname, "port", u.port, "db", u.path, "query", u.query)
t = time.time()
try:
    with psycopg.connect(url, connect_timeout=15) as c:
        print("connected in", round(time.time() - t, 2), "s:", c.execute("SELECT version()").fetchone()[0][:40])
except Exception as e:
    print("FAILED after", round(time.time() - t, 1), "s:", type(e).__name__, str(e)[:300])
