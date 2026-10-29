"""Step 2: gather evidence about a listing, each function is one pipeline step."""
import statistics
from urllib.parse import urljoin
import time
from concurrent.futures import ThreadPoolExecutor

from . import db, llm, tavily
from .config import COMMUNITY_DOMAINS, TRUSTED_STORES
from .listing import normalise_gpu, store_of, structured_offer

MARKET_SYSTEM = ("You read Indian PC store pages and list graphics cards for sale. "
                 "Return JSON only. Prices are integers in rupees.")


def _chip(gpu):
    """'RTX 3060 12GB' -> 'RTX 3060'."""
    return gpu.rsplit(" ", 1)[0] if gpu.endswith("GB") else gpu


def _page_offers(gpu, url, text):
    user = (f"Target card: {gpu}\nPage URL: {url}\n\n"
            "List every product on this page that is the target card: same chip, same "
            "variant (Ti/Super/XT matter) and same memory size. Ignore other cards, "
            "laptops, prebuilt PCs and accessories. At most 15 offers, cheapest first.\n"
            'Return {"offers": [{"product_name": str, "price_inr": int, '
            '"in_stock": bool|null, "product_url": str|null}]}\n\n'
            f"PAGE TEXT:\n{text[:10000]}")
    try:
        data, meta = llm.chat_json("market_prices", MARKET_SYSTEM, user, max_tokens=4000)
    except (ValueError, RuntimeError):  # truncated or malformed output: skip this page
        return [], None
    offers = []
    for o in data.get("offers") or []:
        price = o.get("price_inr")
        if not isinstance(price, int) or price < 3000:
            continue
        found = normalise_gpu(o.get("product_name") or "")
        if found and (_chip(found) != _chip(gpu) or
                      (found.endswith("GB") and gpu.endswith("GB") and found != gpu)):
            continue
        link = o.get("product_url") or url
        if link.startswith("/"):
            link = urljoin(url, link)
        offers.append({**o, "product_url": link, "page_url": url, "store": store_of(url)["name"]})
    return offers, meta


def _verify_stock(offers, limit=10):
    """Collection pages often hide stock. Check the cheapest unknowns on their own pages."""
    todo = sorted((o for o in offers if o.get("in_stock") is None and o.get("product_url")
                   and o["product_url"] != o["page_url"]), key=lambda o: o["price_inr"])[:limit]

    def check(o):
        truth = structured_offer(o["product_url"])
        if truth and truth["in_stock"] is not None:
            o["in_stock"] = truth["in_stock"]
            o["stock_verified"] = True
            if truth["price_inr"]:
                o["price_inr"] = truth["price_inr"]

    with ThreadPoolExecutor(5) as pool:
        list(pool.map(check, todo))


def market_prices(gpu):
    """Same card on trusted Indian stores. Returns (summary, calls)."""
    if not gpu:
        return {"offers": [], "note": "Could not tell which GPU this is."}, []
    results = tavily.search(f"{gpu} graphics card price India", list(TRUSTED_STORES),
                            max_results=8)
    seen, urls = set(), []
    for r in results:
        domain = store_of(r["url"])["domain"]
        if domain in seen and len(urls) >= 4:
            continue
        seen.add(domain)
        urls.append(r["url"])
    urls = urls[:6]
    pages = tavily.extract(urls) if urls else {}
    calls, offers = [], []
    with ThreadPoolExecutor(6) as pool:
        for found, meta in pool.map(lambda kv: _page_offers(gpu, *kv),
                                    [(u, t) for u, t in pages.items() if t]):
            offers.extend(found)
            if meta:
                calls.append(meta)
    _verify_stock(offers)
    dedup = {}
    for o in offers:
        k = (o["store"], o["product_name"].lower()[:60], o["price_inr"])
        dedup[k] = o
    offers = sorted(dedup.values(), key=lambda o: o["price_inr"])
    # Cheapest offer from each store first, so the table spans stores.
    firsts, rest, stores = [], [], set()
    for o in offers:
        (rest if o["store"] in stores else firsts).append(o)
        stores.add(o["store"])
    offers = sorted(firsts, key=lambda o: (not o.get("in_stock"), o["price_inr"])) + rest
    in_stock = [o["price_inr"] for o in offers if o.get("in_stock")]
    summary = {
        "offers": offers[:12],
        "stores_checked": sorted({store_of(u)["name"] for u in urls}),
        "in_stock_count": len(in_stock),
        "median_in_stock_inr": int(statistics.median(in_stock)) if in_stock else None,
        "lowest_in_stock_inr": min(in_stock) if in_stock else None,
    }
    return summary, calls


COMMUNITY_SYSTEM = ("You check what Indian PC buyers say online about a seller or listing. "
                    "Use only the search snippets given. Return JSON only.")


def community(listing):
    """Forum and review reports about the seller and this kind of listing."""
    seller = (listing.get("seller") or "").replace("Sold by", "").strip()
    store = listing.get("store") or ""
    queries = []
    if seller and store_of(listing.get("url", ""))["kind"] == "marketplace":
        queries.append((f'"{seller}" seller {store} review', None))
    queries.append((f"{store} graphics card seller fake refurbished notify me experience",
                    COMMUNITY_DOMAINS))
    if listing.get("gpu"):
        queries.append((f"{listing['gpu']} price India {store} worth buying", COMMUNITY_DOMAINS))
    snippets = []
    for q, domains in queries:
        for r in tavily.search(q, domains, max_results=5):
            snippets.append({"url": r["url"], "title": r.get("title"),
                             "snippet": (r.get("content") or "")[:600]})
    if not snippets:
        return {"reports": [], "summary": "No community discussion found."}, []
    user = (f"Seller: {seller or 'unknown'}\nStore: {store}\nCard: {listing.get('gpu')}\n\n"
            "From the snippets, list reports that are relevant to this seller, this store's "
            "GPU listings, or this card's pricing in India. Skip anything unrelated.\n"
            'Return {"reports": [{"url": str, "claim": str, "tone": "positive"|"negative"|'
            '"neutral", "about": "seller"|"store"|"card"}], "summary": str}\n\n'
            + "\n\n".join(f"[{i}] {s['title']}\n{s['url']}\n{s['snippet']}"
                          for i, s in enumerate(snippets)))
    data, meta = llm.chat_json("community", COMMUNITY_SYSTEM, user, max_tokens=1500)
    data["searched"] = [q for q, _ in queries]
    return data, [meta]


def warranty(listing):
    """Snippets on the brand's authorised sellers in India, for the verdict to weigh."""
    brand = listing.get("brand")
    if not brand:
        return {"snippets": []}, []
    results = tavily.search(f"{brand} graphics card India authorised distributor warranty "
                            "third party seller", max_results=5, ttl_s=7 * 86400)
    return {"brand": brand, "snippets": [
        {"url": r["url"], "title": r.get("title"), "snippet": (r.get("content") or "")[:500]}
        for r in results]}, []


def history(url):
    """What the watcher has seen for this URL."""
    with db.conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT ts, price_inr, in_stock, availability FROM snapshots WHERE url=? ORDER BY ts",
            (url,))]
    if not rows:
        return {"snapshots": 0, "points": []}, []
    stocked = [r for r in rows if r["in_stock"]]
    prices = [r["price_inr"] for r in rows if r["price_inr"]]
    return {
        "snapshots": len(rows),
        "first_seen": rows[0]["ts"],
        "days_tracked": round((time.time() - rows[0]["ts"]) / 86400, 1),
        "times_in_stock": len(stocked),
        "ever_in_stock_at_price": bool(stocked),
        "price_min": min(prices) if prices else None,
        "price_max": max(prices) if prices else None,
        "points": [{"ts": r["ts"], "price_inr": r["price_inr"], "in_stock": r["in_stock"]}
                   for r in rows[-120:]],
    }, []


def signals(listing, market, hist):
    """Plain numeric red flags, computed without a model."""
    out = []
    price, mrp = listing.get("price_inr"), listing.get("mrp_inr")
    median = market.get("median_in_stock_inr")
    if price and median:
        pct = round(100 * (price - median) / median)
        out.append({"id": "price_vs_market", "value": pct,
                    "text": f"{abs(pct)}% {'above' if pct > 0 else 'below'} the trusted-store median"})
    if price and mrp and mrp > price:
        pct = round(100 * (mrp - price) / mrp)
        out.append({"id": "mrp_discount", "value": pct, "text": f"Claims {pct}% off MRP"})
    if listing.get("in_stock") is False:
        out.append({"id": "not_buyable", "value": True,
                    "text": f"Not buyable now ({listing.get('availability_text')})"})
    if listing.get("returnable") is False:
        out.append({"id": "non_returnable", "value": True, "text": "Non-returnable"})
    if hist.get("snapshots", 0) >= 3:
        out.append({"id": "history", "value": hist["times_in_stock"],
                    "text": f"In stock {hist['times_in_stock']} of {hist['snapshots']} checks "
                            f"over {hist['days_tracked']} days"})
    return out
