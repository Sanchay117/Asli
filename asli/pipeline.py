"""The deal check: read, gather evidence in parallel, decide. Yields events as it goes."""
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import db, evidence, listing as listing_mod, llm, verdict
from .llm import SpendCapReached

RESULT_TTL_S = 3600


def _step(step_id, label, status, **extra):
    return {"type": "step", "id": step_id, "label": label, "status": status, **extra}


def _cost(calls):
    return sum(c["cost_usd"] for c in calls)


def track(lst):
    """Every checked listing joins the watchlist, so history builds for the next person."""
    with db.conn() as c:
        count = c.execute("SELECT COUNT(*) FROM tracked").fetchone()[0]
        if count < 80:
            c.execute("INSERT OR IGNORE INTO tracked VALUES (?,?,?,?,?)",
                      (lst["url"], lst.get("store"), lst.get("title"), lst.get("gpu"), time.time()))


def snapshot(lst, page_hash):
    with db.conn() as c:
        c.execute("INSERT INTO snapshots (ts,url,store,title,price_inr,mrp_inr,in_stock,"
                  "availability,seller,page_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (time.time(), lst["url"], lst.get("store"), lst.get("title"),
                   lst.get("price_inr"), lst.get("mrp_inr"),
                   None if lst.get("in_stock") is None else int(lst["in_stock"]),
                   lst.get("availability_text"), lst.get("seller"), page_hash))


def run_check(url=None, text=None, image=None):
    if url:
        url = listing_mod.canonical(url)
    cache_key = f"check:{url}" if url and not text and not image else None
    if cache_key:
        hit = db.cache_get(cache_key, RESULT_TTL_S)
        if hit:
            hit["cached"] = True
            yield {"type": "cached"}
            yield hit
            return
    all_calls = []
    t0 = time.time()
    try:
        yield _step("read", "Reading the listing", "running")
        if image:
            lst, calls, page_hash = listing_mod.read_image(image, url or "")
        elif text:
            lst, calls, page_hash = listing_mod.read_text(text, url or "")
        else:
            lst, calls, page_hash = listing_mod.read_listing(url)
        all_calls += calls
        if url and not text:
            snapshot(lst, page_hash)
        yield _step("read", "Reading the listing", "done", calls=calls, method=lst.get("method"),
                    summary=f"{lst.get('title') or 'Unknown item'}: "
                            f"₹{lst.get('price_inr') or '?'} at {lst.get('store')}",
                    data=lst)
        if lst.get("is_product_page") is False:
            yield {"type": "error", "message": "That looks like a category or search page. "
                                               "Paste a link to a single product."}
            return

        jobs = {
            "market": ("Checking trusted Indian stores", lambda: evidence.market_prices(lst.get("gpu"))),
            "community": ("Searching forums for seller reports", lambda: evidence.community(lst)),
            "warranty": ("Looking up warranty rules", lambda: evidence.warranty(lst)),
            "history": ("Checking watch history", lambda: evidence.history(lst["url"]) if lst.get("url")
                        else ({"snapshots": 0, "points": []}, [])),
        }
        for k, (label, _) in jobs.items():
            yield _step(k, label, "running")
        found = {}
        with ThreadPoolExecutor(4) as pool:
            futures = {pool.submit(fn): k for k, (_, fn) in jobs.items()}
            for f in as_completed(futures):
                k = futures[f]
                try:
                    data, calls = f.result()
                except SpendCapReached:
                    raise
                except Exception as e:  # one weak source should not sink the check
                    data, calls = {"error": str(e)[:200]}, []
                found[k] = data
                all_calls += calls
                yield _step(k, jobs[k][0], "error" if "error" in data else "done",
                            calls=calls, data=data, summary=_summary(k, data))

        sig = evidence.signals(lst, found["market"], found["history"])
        yield _step("verdict", "Weighing the evidence", "running")
        decision, meta = verdict.decide(lst, found["market"], found["community"],
                                        found["warranty"], found["history"], sig)
        all_calls.append(meta)
        yield _step("verdict", "Weighing the evidence", "done", calls=[meta],
                    summary=decision.get("headline"))
    except listing_mod.NeedScreenshot as e:
        yield {"type": "need_screenshot", "message": str(e)}
        return
    except SpendCapReached as e:
        yield {"type": "error", "message": f"Asli paused itself: {e}. This protects the demo budget."}
        return
    except Exception as e:
        yield {"type": "error", "message": str(e)[:300]}
        return

    if url and not text:
        track(lst)
    ultra_equiv = sum(llm.cost_of("ultra", c["prompt_tokens"], c["completion_tokens"])
                      for c in all_calls)
    result = {
        "type": "result",
        "listing": lst, "market": found["market"], "community": found["community"],
        "history": found["history"], "signals": sig, "verdict": decision,
        "usage": {
            "calls": len(all_calls),
            "cost_usd": _cost(all_calls),
            "all_ultra_cost_usd": ultra_equiv,
            "tokens": sum(c["prompt_tokens"] + c["completion_tokens"] for c in all_calls),
            "seconds": round(time.time() - t0, 1),
            "by_model": _by_model(all_calls),
        },
        "checked_at": time.time(),
    }
    with db.conn() as c:
        c.execute("INSERT INTO checks (ts,url,verdict,result) VALUES (?,?,?,?)",
                  (time.time(), url, decision.get("verdict"), json.dumps(result, default=str)))
    if cache_key:
        db.cache_put(cache_key, result)
    yield result


def _by_model(calls):
    out = {}
    for c in calls:
        m = out.setdefault(c["model"], {"calls": 0, "tokens": 0, "cost_usd": 0.0})
        m["calls"] += 1
        m["tokens"] += c["prompt_tokens"] + c["completion_tokens"]
        m["cost_usd"] += c["cost_usd"]
    return out


def _summary(kind, data):
    if "error" in data:
        return "Source unavailable, continuing without it"
    if kind == "market":
        n = len(data.get("offers", []))
        med = data.get("median_in_stock_inr")
        return f"{n} offers found" + (f", median in stock ₹{med:,}" if med else ", none in stock")
    if kind == "community":
        return f"{len(data.get('reports', []))} relevant reports"
    if kind == "warranty":
        return f"{len(data.get('snippets', []))} sources on {data.get('brand') or 'brand'} warranty"
    if kind == "history":
        n = data.get("snapshots", 0)
        return "First time Asli has seen this listing" if n <= 1 else \
            f"Seen {n} times, in stock {data['times_in_stock']} times"
    return ""
