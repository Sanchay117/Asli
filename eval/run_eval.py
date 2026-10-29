"""Measure each Nemotron setup on Asli's tasks and write the routing table.

No hand labels:
- read_listing: trusted-store product pages, scored against the schema.org price and
  stock data the store publishes in the same page.
- verdict: scenarios built from real listings where the right call follows from clear
  rules (not buyable + inflated MRP = bait, double the market price = overpriced, ...).

Usage: python -m eval.run_eval [--collect]
"""
import argparse
import copy
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

from asli import llm, tavily
from asli.config import DATA_DIR, TRUSTED_STORES
from asli.listing import extract_with_model, normalise_gpu, store_of, structured_offer
from asli.verdict import SCHEMA, SYSTEM as VERDICT_SYSTEM

CASES_FILE = DATA_DIR / "eval_cases.json"
GPUS = ["RTX 3060 12GB", "RTX 4060 8GB", "RTX 5060 8GB", "RTX 5060 Ti 16GB", "RTX 5070 12GB",
        "RX 7600 8GB", "RX 9060 XT 16GB", "RTX 3050 6GB"]
TOLERANCE = 2.0  # accuracy points

NOTES = [
    "Nano with reasoning off misread about 1 in 6 prices. In a product about prices that is too many, so reading runs on Ultra with reasoning off: more accurate, and still only a fraction of a cent per page.",
    "Turning Nemotron reasoning off cut output tokens about 7x on extraction, with the same answers on Ultra.",
    "Super with JSON mode and reasoning off returned {} or looped on escaped JSON on this endpoint. Asli retries without JSON mode, but Super stayed unreliable for this task.",
    "Forum summaries are not price-critical and stay on Nano.",
]

READ_SETUPS = [("nano", False), ("nano", True), ("super", False), ("ultra", False)]
VERDICT_SETUPS = [("nano", True), ("super", True), ("ultra", False), ("ultra", True)]


# ---------- collect read_listing cases ----------

def collect(target=40):
    urls = []
    for gpu in GPUS:
        for domain in ["vedantcomputers.com", "mdcomputers.in", "primeabgb.com", "elitehubs.com"]:
            for r in tavily.search(f"{gpu} graphics card", [domain], max_results=3, ttl_s=86400):
                u = r["url"]
                if any(k in u for k in ("collection", "catalog", "/c/", "buy-online-price")):
                    continue
                urls.append(u)
    urls = list(dict.fromkeys(urls))
    cases = []
    for u in urls:
        truth = structured_offer(u)
        if truth and truth["price_inr"] and truth["in_stock"] is not None:
            cases.append({"url": u, "truth": truth})
        if len(cases) >= target:
            break
        time.sleep(0.5)
    texts = {}
    for i in range(0, len(cases), 5):
        texts.update(tavily.extract([c["url"] for c in cases[i:i + 5]], ttl_s=86400))
    cases = [dict(c, text=texts[c["url"]]) for c in cases if answerable(c, texts.get(c["url"]))]
    CASES_FILE.write_text(json.dumps(cases, ensure_ascii=False))
    print(f"collected {len(cases)} read_listing cases")
    return cases


def answerable(case, text):
    """Only score pages whose text actually states the price."""
    if not text:
        return False
    p = case["truth"]["price_inr"]
    s = str(p)
    indian = (s[:-3] and f"{int(s[:-3]):,}".replace(",", "") and
              ",".join([s[:-3][::-1][i:i + 2][::-1] for i in range(0, len(s[:-3]), 2)][::-1]) + "," + s[-3:]) or s
    flat = text.replace(" ", "")
    return any(f in flat for f in (f"{p:,}", s, indian))


# ---------- verdict scenarios ----------

def base_listing(**kw):
    lst = {"title": "MSI GeForce RTX 3060 Ventus 2X 12GB OC", "brand": "MSI", "gpu": "RTX 3060 12GB",
           "price_inr": 26000, "mrp_inr": 31000, "in_stock": True, "availability_text": "In Stock",
           "seller": "Vedant Computers", "fulfilled_by_platform": None, "returnable": True,
           "warranty_text": "3 Years", "store": "Vedant Computers", "store_kind": "trusted"}
    lst.update(kw)
    return lst


MARKET = {"median_in_stock_inr": 26000, "lowest_in_stock_inr": 23900, "in_stock_count": 9,
          "stores_checked": ["EliteHubs", "MD Computers", "PrimeABGB", "Vedant Computers"],
          "offers": [{"store": "EliteHubs", "product_name": "INNO3D RTX 3060 Twin X2 12GB",
                      "price_inr": 23900, "in_stock": True},
                     {"store": "MD Computers", "product_name": "Zotac RTX 3060 Twin Edge 12GB",
                      "price_inr": 25500, "in_stock": True},
                     {"store": "PrimeABGB", "product_name": "MSI RTX 3060 Ventus 2X 12GB",
                      "price_inr": 27800, "in_stock": False}]}

SCENARIOS = [
    ("not buyable, 66% off inflated MRP", ["likely_bait"],
     base_listing(store="Flipkart", store_kind="marketplace", price_inr=21000, mrp_inr=62000,
                  in_stock=False, availability_text="Notify Me", seller=None)),
    ("never in stock over 12 days", ["likely_bait"],
     base_listing(store="Flipkart", store_kind="marketplace", price_inr=19999, mrp_inr=45000,
                  in_stock=False, availability_text="Coming Soon", seller=None),
     {"snapshots": 40, "times_in_stock": 0, "days_tracked": 12, "ever_in_stock_at_price": False}),
    ("double the market, non-returnable 3P seller", ["overpriced"],
     base_listing(store="Amazon.in", store_kind="marketplace", price_inr=52000, mrp_inr=52000,
                  seller="PC PARTS DEALER", returnable=False)),
    ("40% above market on a trusted store", ["overpriced"],
     base_listing(price_inr=36500, mrp_inr=60000)),
    ("at market price, trusted store", ["fair", "good_deal"], base_listing()),
    ("4% below market, trusted store", ["good_deal", "fair"], base_listing(price_inr=24900)),
    ("12% below market, trusted, in stock", ["good_deal"], base_listing(price_inr=22900)),
    ("45% below market from a new 3P seller, non-returnable", ["suspicious"],
     base_listing(store="Amazon.in", store_kind="marketplace", price_inr=14300, mrp_inr=40000,
                  seller="TechDealz Retail", returnable=False, warranty_text=None)),
    ("used-looking OLX style post far below market", ["suspicious"],
     base_listing(store="olx.in", store_kind="unknown", price_inr=11000, mrp_inr=None,
                  seller="private seller", returnable=False, warranty_text=None,
                  title="RTX 3060 12GB brand new sealed urgent sale")),
    ("Flipkart Assured, at market, in stock", ["fair", "good_deal"],
     base_listing(store="Flipkart", store_kind="marketplace", price_inr=26500, mrp_inr=36000,
                  seller=None, fulfilled_by_platform=True)),
    ("in stock 1 of 30 checks, low price", ["likely_bait", "suspicious"],
     base_listing(store="Flipkart", store_kind="marketplace", price_inr=20500, mrp_inr=58000,
                  in_stock=False, availability_text="Notify Me", seller=None),
     {"snapshots": 30, "times_in_stock": 1, "days_tracked": 9, "ever_in_stock_at_price": True}),
    ("15% above market, 3P seller, returnable", ["overpriced", "fair"],
     base_listing(store="Amazon.in", store_kind="marketplace", price_inr=29900, mrp_inr=35000,
                  seller="Cloudtail-like seller", returnable=True)),
]


def scenario_evidence(listing, hist=None):
    from asli.evidence import signals
    hist = hist or {"snapshots": 0}
    return {"listing": listing, "red_flag_signals": signals(listing, MARKET, hist),
            "trusted_store_prices": MARKET, "community_reports": {"reports": [], "summary": "none"},
            "warranty_context": {}, "watch_history": hist}


# ---------- runners ----------

def score_read(case, tier, think):
    store = store_of(case["url"])
    data, meta = extract_with_model_tier(case["text"], case["url"], store, tier, think)
    t = case["truth"]
    price = data.get("price_inr")
    price_ok = isinstance(price, (int, float)) and abs(price - t["price_inr"]) <= 0.01 * t["price_inr"]
    stock_ok = data.get("in_stock") == t["in_stock"]
    return (price_ok + stock_ok) / 2, meta


def extract_with_model_tier(text, url, store, tier, think):
    from asli.listing import FIELDS, SYSTEM, _trim
    user = (f"Store: {store['name']}\nURL: {url}\n\nReturn JSON with exactly these fields:\n"
            f"{FIELDS}\n\nPAGE TEXT:\n{_trim(text)}")
    return llm.chat_json("eval_read_listing", SYSTEM, user, tier=tier, think=think,
                         max_tokens=6000 if think else 1500)


def score_verdict(sc, tier, think):
    name, ok_labels, listing = sc[0], sc[1], sc[2]
    hist = sc[3] if len(sc) > 3 else None
    ev = scenario_evidence(copy.deepcopy(listing), hist)
    user = (f"Evidence:\n{json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
            f"Return JSON matching:\n{SCHEMA}")
    data, meta = llm.chat_json("eval_verdict", VERDICT_SYSTEM, user, tier=tier, think=think,
                               max_tokens=6000)
    return float(data.get("verdict") in ok_labels), meta


def run(task, items, setups, scorer):
    rows = []
    for tier, think in setups:
        def one(item):
            try:
                return scorer(item, tier, think)
            except Exception as e:
                print("   error", tier, think, str(e)[:100])
                return 0.0, None
        with ThreadPoolExecutor(6) as pool:
            out = list(pool.map(one, items))
        metas = [m for _, m in out if m]
        row = {
            "task": task, "tier": tier, "think": think,
            "accuracy": sum(s for s, _ in out) / len(out),
            "cost_per_call": statistics.mean(m["cost_usd"] for m in metas) if metas else 0,
            "latency_s": statistics.mean(m["latency_s"] for m in metas) if metas else 0,
            "out_tokens": statistics.mean(m["completion_tokens"] for m in metas) if metas else 0,
            "n": len(out),
        }
        rows.append(row)
        print(f"  {task:13} {tier:5} think={think!s:5} acc={row['accuracy']:.0%} "
              f"${row['cost_per_call']:.5f}/call {row['latency_s']:.1f}s")
    best = max(r["accuracy"] for r in rows)
    eligible = [r for r in rows if r["accuracy"] >= best - TOLERANCE / 100]
    chosen = min(eligible, key=lambda r: r["cost_per_call"])
    chosen["chosen"] = True
    return rows, chosen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect", action="store_true")
    a = ap.parse_args()
    cases = collect() if a.collect or not CASES_FILE.exists() else json.loads(CASES_FILE.read_text())
    print(f"read_listing: {len(cases)} cases, verdict: {len(SCENARIOS)} scenarios")

    read_rows, read_pick = run("read_listing", cases, READ_SETUPS, score_read)
    verdict_rows, verdict_pick = run("verdict", SCENARIOS, VERDICT_SETUPS, score_verdict)

    # Forum summaries are not price-critical and were not scored, so they stay on Nano.
    routing = {"read_listing": read_pick["tier"], "market_prices": read_pick["tier"],
               "community": "nano", "verdict": verdict_pick["tier"]}
    thinking = {"read_listing": read_pick["think"], "verdict": verdict_pick["think"]}
    results = {
        "description": (f"read_listing: {len(cases)} real trusted-store pages, scored on price and "
                        "stock against the store's own schema.org data. verdict: "
                        f"{len(SCENARIOS)} scenarios with rule-defined correct calls."),
        "cases": len(cases) + len(SCENARIOS),
        "tolerance_pct": TOLERANCE,
        "run_at": time.strftime("%d %b %Y %H:%M"),
        "results": read_rows + verdict_rows,
        "routing": routing, "thinking": thinking,
        "notes": NOTES,
    }
    (DATA_DIR / "eval_results.json").write_text(json.dumps(results, indent=1))
    (DATA_DIR / "routing.json").write_text(json.dumps({"routing": routing, "thinking": thinking}, indent=1))
    print("routing:", routing, "thinking:", thinking)


if __name__ == "__main__":
    main()
