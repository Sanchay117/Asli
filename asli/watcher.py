"""Background watcher: revisit tracked listings, record price and stock, alert on real stock.

python -m asli.watcher --seed        find popular GPU listings to track
python -m asli.watcher --once        one pass over the watchlist
python -m asli.watcher --loop 3      a pass every 3 hours
python -m asli.watcher --loop 2 --only flipkart.com   only one store (the hosted app
                                     cannot reach Flipkart, so a home machine covers it)
"""
import argparse
import random
import time

import requests

from . import db, tavily
from .config import NTFY_TOPIC, TRUSTED_STORES
from .listing import (canonical, fetch_flipkart, normalise_gpu, read_listing, store_of,
                      structured_offer)
from .pipeline import snapshot

SEED_GPUS = ["RTX 3060 12GB", "RTX 4060 8GB", "RTX 5060 8GB", "RTX 5060 Ti 16GB",
             "RTX 5070 12GB", "RX 7600 8GB", "RX 9060 XT 16GB", "ARC B580 12GB"]


def _add(url, store, label, gpu):
    url = canonical(url)
    with db.conn() as c:
        c.execute("INSERT OR IGNORE INTO tracked VALUES (?,?,?,?,?)",
                  (url, store, label, gpu, time.time()))


def seed():
    added = 0
    for gpu in SEED_GPUS:
        for r in tavily.search(f"{gpu} graphics card", ["flipkart.com"], max_results=5, ttl_s=86400):
            if "/p/" in r["url"] and normalise_gpu(r.get("title", "")) == gpu:
                _add(r["url"].split("?")[0], "Flipkart", r.get("title"), gpu)
                added += 1
        for r in tavily.search(f"{gpu} graphics card price", list(TRUSTED_STORES),
                               max_results=6, ttl_s=86400):
            title = r.get("title", "")
            if normalise_gpu(title) != gpu or "collection" in r["url"] or "catalog" in r["url"]:
                continue
            offer = structured_offer(r["url"])
            if offer and offer["price_inr"]:
                _add(r["url"], store_of(r["url"])["name"], offer["name"] or title, gpu)
                added += 1
            time.sleep(1)
    print(f"seeded {added} listings")


def _last(url):
    with db.conn() as c:
        row = c.execute("SELECT in_stock, price_inr FROM snapshots WHERE url=? ORDER BY ts DESC LIMIT 1",
                        (url,)).fetchone()
    return dict(row) if row else None


def notify(title, body, url):
    if not NTFY_TOPIC:
        return
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=body.encode(),
                      headers={"Title": title, "Click": url, "Tags": "white_check_mark"}, timeout=10)
    except requests.RequestException:
        pass


def observe(url):
    """One look at a listing without spending model tokens where possible."""
    store = store_of(url)
    if store["domain"] == "flipkart.com":
        lst, page_hash = fetch_flipkart(url)
        if lst:
            lst.update(url=url, store="Flipkart")
            return lst, page_hash
        return None, None
    if store["kind"] == "trusted":
        offer = structured_offer(url)
        if offer and offer["price_inr"]:
            return {"url": url, "store": store["name"], "title": offer["name"],
                    "price_inr": offer["price_inr"], "in_stock": offer["in_stock"],
                    "availability_text": offer["availability"]}, None
    # Other stores (Amazon etc.) need Tavily + Nano, so only every few passes.
    lst, _, page_hash = read_listing(url)
    return lst, page_hash


def run_once(pass_no=0, only=None):
    with db.conn() as c:
        tracked = [dict(r) for r in c.execute("SELECT * FROM tracked")]
    if only:
        tracked = [t for t in tracked if store_of(t["url"])["domain"] == only]
    seen = changed = 0
    for t in tracked:
        url = t["url"]
        kind = store_of(url)["kind"]
        if kind not in ("trusted",) and store_of(url)["domain"] != "flipkart.com" and pass_no % 4:
            continue
        before = _last(url)
        try:
            lst, page_hash = observe(url)
        except Exception as e:  # keep going; one bad page should not stop the pass
            print("  skip", url[:80], type(e).__name__, str(e)[:80])
            continue
        if not lst:
            continue
        snapshot(lst, page_hash)
        seen += 1
        if before and not before["in_stock"] and lst.get("in_stock"):
            changed += 1
            notify(f"Back in stock: {t.get('gpu') or ''} at {lst['store']}",
                   f"{lst.get('title', '')[:90]} is buyable now for ₹{lst.get('price_inr')}", url)
        time.sleep(random.uniform(1.5, 3.5))
    print(time.strftime("%H:%M"), f"pass {pass_no}: {seen}/{len(tracked)} listings, {changed} back in stock")
    return seen


def loop(hours, only=None):
    n = 0
    while True:
        try:
            run_once(n, only)
        except Exception as e:
            print("pass failed:", e)
        n += 1
        time.sleep(hours * 3600)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", type=float)
    ap.add_argument("--only", help="limit to one store domain, e.g. flipkart.com")
    a = ap.parse_args()
    if a.seed:
        seed()
    if a.once:
        run_once(only=a.only)
    if a.loop:
        loop(a.loop, a.only)
