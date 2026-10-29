"""Step 3: weigh the evidence and decide."""
import json

from . import llm

SYSTEM = """You are Asli, a careful advisor for Indian PC part buyers. You decide whether a
graphics card listing is a deal worth acting on, using only the evidence given.

Patterns you know about:
- Bait listings: a low price with "Notify Me" or "out of stock" that never becomes buyable,
  often with an inflated MRP so the discount looks huge.
- Third-party marketplace sellers charging far above trusted stores, sometimes non-returnable,
  sometimes without valid brand warranty.
- Refurbished or grey-import cards sold as new.
Trusted Indian stores (MD Computers, PrimeABGB, Vedant, EliteHubs, The IT Depot) are the
reference for fair price and real stock.

Be concrete and fair: a good listing should be called good. Never invent facts or sources.
Watch history with fewer than 3 snapshots says nothing yet; do not draw conclusions from it.
Report community claims exactly as strong as the snippets make them, name them as
claims ("some Reddit users say"), and never let a few forum posts outweigh hard facts like
price, stock and returns. Trusted stores can still be overpriced for a specific card; say
so plainly, but do not call a trusted store itself dishonest.
Write plain sentences without em dashes. Return JSON only."""

SCHEMA = """{
  "verdict": "good_deal" | "fair" | "overpriced" | "suspicious" | "likely_bait",
  "trust_score": int,            // 0-100, how safe it is to act on this listing
  "headline": str,               // max 12 words, plain language
  "summary": str,                // 2-3 sentences
  "reasons": [{"label": str, "detail": str, "severity": "good"|"warn"|"bad",
               "source_url": str|null}],     // 3-5 reasons, most important first
  "recommendation": {"action": "buy" | "wait" | "avoid" | "buy_elsewhere",
                     "offer_index": int|null,   // index into trusted_store_prices.offers
                     "why": str}
}"""


def decide(listing, market, community, warranty, history, signals):
    evidence = {
        "listing": {k: v for k, v in listing.items() if k not in ("raw_status",)},
        "red_flag_signals": signals,
        "trusted_store_prices": market,
        "community_reports": community,
        "warranty_context": warranty,
        "watch_history": {k: v for k, v in history.items() if k != "points"},
    }
    user = (f"Evidence:\n{json.dumps(evidence, ensure_ascii=False, default=str)[:24000]}\n\n"
            f"Return JSON matching:\n{SCHEMA}\n"
            "For buy_elsewhere, set offer_index to the cheapest in-stock trusted offer of the "
            "same card. source_url must be a URL that appears in the evidence, or null.")
    decision, meta = llm.chat_json("verdict", SYSTEM, user, max_tokens=6000,
                                    think=llm.thinking("verdict", True))
    return _ground(decision, evidence), meta


def _ground(decision, evidence):
    """Keep only links that came from the evidence; resolve the offer the model picked."""
    blob = json.dumps(evidence, default=str)
    for r in decision.get("reasons") or []:
        if r.get("source_url") and r["source_url"] not in blob:
            r["source_url"] = None
        for k in ("label", "detail"):
            r[k] = _plain(r.get(k))
    for k in ("headline", "summary"):
        decision[k] = _plain(decision.get(k))
    rec = decision.setdefault("recommendation", {})
    rec["why"] = _plain(rec.get("why"))
    offers = (evidence.get("trusted_store_prices") or {}).get("offers") or []
    listing = evidence["listing"]
    price = listing.get("price_inr") or 0
    buyable = listing.get("in_stock") is not False

    def better(o):
        # An alternative must be in stock, a different page, and cheaper (unless this
        # listing cannot be bought at all).
        return (o.get("in_stock") and o.get("product_url") != listing.get("url")
                and (not buyable or not price or o["price_inr"] < price))

    i = rec.get("offer_index")
    pick = offers[i] if isinstance(i, int) and 0 <= i < len(offers) else None
    if not (pick and better(pick)):
        pick = min((o for o in offers if better(o)), key=lambda o: o["price_inr"], default=None)
    rec["offer"] = pick
    if rec.get("action") == "buy_elsewhere" and not pick:
        rec["action"] = "wait"
    return decision


def _plain(text):
    return text.replace(" \u2014 ", ", ").replace("\u2014", ", ") if isinstance(text, str) else text
