"""Asli web app: streams deal checks to the browser and serves the dashboard data."""
import json
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from asli import db, llm
from asli.config import (DATA_DIR, MODELS, MONTHLY_CAP_USD, ROOT, SPEND_CAP_USD,
                         TAVILY_MONTHLY_CREDITS)
from asli.pipeline import run_check

app = FastAPI(title="Asli")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

CHECKS_PER_HOUR = 12
_recent = defaultdict(deque)

EXAMPLES = [
    {"label": "Flipkart RTX 3060 at ₹28,839",
     "url": "https://www.flipkart.com/gigabyte-geforce-rtx-3060-pci-e-x16-windforce-oc-12gd-gv-n3060wf2oc-12gd-gddr6-12-gb-nvidia-chipset-192-bit-1792-mhz-graphics-card/p/itmabe6891376c4e"},
    {"label": "Amazon RTX 3060 at ₹58,249",
     "url": "https://www.amazon.in/GIGABYTE-WINDFORCE-pci_e_x16-Graphics-GV-N3060WF2OC-12GD/dp/B0BNP2CMXM"},
    {"label": "Vedant RTX 3060 at ₹51,490",
     "url": "https://www.vedantcomputers.com/msi-geforce-rtx-3060-ventus-2x-12gb-oc-gddr6"},
]


class CheckIn(BaseModel):
    url: str | None = None
    text: str | None = None


def _rate_limit(request: Request):
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?")
    ip = ip.split(",")[0].strip()
    q, now = _recent[ip], time.time()
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= CHECKS_PER_HOUR:
        raise HTTPException(429, "You have run a lot of checks this hour. Try again a bit later.")
    q.append(now)


WATCH_TOKEN = os.environ.get("WATCH_TOKEN", "")
WATCH_EVERY_S = 110 * 60
_watch_lock = threading.Lock()


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/api/watch/run")
def watch_run(request: Request):
    """Called by a scheduled job: start one watcher pass in the background."""
    if not WATCH_TOKEN or request.headers.get("x-watch-token") != WATCH_TOKEN:
        raise HTTPException(403, "Forbidden")
    # Snapshots also come from user checks, so passes keep their own marker.
    if db.cache_get("watch:last_pass", WATCH_EVERY_S):
        return {"started": False, "reason": "last pass was recent"}
    if not _watch_lock.acquire(blocking=False):
        return {"started": False, "reason": "a pass is already running"}

    def work():
        from asli.watcher import run_once
        try:
            db.cache_put("watch:last_pass", time.time())
            run_once(int(time.time() // 7200))
        finally:
            _watch_lock.release()

    threading.Thread(target=work, daemon=True).start()
    return {"started": True}


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.post("/api/check")
def check(body: CheckIn, request: Request):
    url = (body.url or "").strip() or None
    text = (body.text or "").strip() or None
    if not url and not text:
        raise HTTPException(400, "Paste a listing link or the listing text.")
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    _rate_limit(request)

    def stream():
        for ev in run_check(url=url, text=text):
            yield f"data: {json.dumps(ev, default=str, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/examples")
def examples():
    return EXAMPLES


@app.get("/api/watchlist")
def watchlist():
    with db.conn() as c:
        rows = [dict(r) for r in c.execute("""
            SELECT t.url, t.store, t.label, t.gpu,
                   COUNT(s.id) AS checks,
                   SUM(CASE WHEN s.in_stock=1 THEN 1 ELSE 0 END) AS in_stock_checks,
                   MIN(s.ts) AS first_ts, MAX(s.ts) AS last_ts,
                   MIN(s.price_inr) AS price_min, MAX(s.price_inr) AS price_max
            FROM tracked t LEFT JOIN snapshots s ON s.url = t.url
            GROUP BY t.url ORDER BY t.gpu, t.store""")]
        for r in rows:
            last = c.execute("SELECT price_inr, in_stock, availability FROM snapshots "
                             "WHERE url=? ORDER BY ts DESC LIMIT 1", (r["url"],)).fetchone()
            r.update(dict(last) if last else {})
            r["points"] = [dict(p) for p in c.execute(
                "SELECT ts, price_inr, in_stock FROM snapshots WHERE url=? ORDER BY ts", (r["url"],))]
    return rows


@app.get("/api/stats")
def stats():
    totals = db.spend_totals()
    with db.conn() as c:
        checks = c.execute("SELECT COUNT(*) FROM checks").fetchone()[0]
        verdicts = [dict(r) for r in c.execute(
            "SELECT verdict, COUNT(*) n FROM checks GROUP BY verdict ORDER BY n DESC")]
        snaps = c.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    eval_file = DATA_DIR / "eval_results.json"
    return {
        **totals,
        "caps": {"total_usd": SPEND_CAP_USD, "month_usd": MONTHLY_CAP_USD,
                 "tavily_credits_month": TAVILY_MONTHLY_CREDITS},
        "routing": llm.routing(),
        "models": {k: {"label": v["label"], "id": v["id"], "price": v["price"]}
                   for k, v in MODELS.items()},
        "checks": checks, "verdicts": verdicts, "snapshots": snaps,
        "eval": json.loads(eval_file.read_text()) if eval_file.exists() else None,
    }
