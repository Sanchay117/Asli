"""Show where models disagree with the answer key on read_listing cases.

Usage: python -m eval.diagnose <tier> [think]
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor

from asli.listing import store_of
from eval.run_eval import CASES_FILE, extract_with_model_tier

tier = sys.argv[1]
think = len(sys.argv) > 2
cases = json.loads(CASES_FILE.read_text())


def one(c):
    try:
        d, _ = extract_with_model_tier(c["text"], c["url"], store_of(c["url"]), tier, think)
    except Exception as e:
        return c, {"error": str(e)[:120]}
    return c, d


with ThreadPoolExecutor(6) as pool:
    for c, d in pool.map(one, cases):
        t = c["truth"]
        if "error" in d:
            print("ERR", d["error"]); continue
        p_ok = isinstance(d.get("price_inr"), (int, float)) and abs(d["price_inr"] - t["price_inr"]) <= .01 * t["price_inr"]
        s_ok = d.get("in_stock") == t["in_stock"]
        if not (p_ok and s_ok):
            print(f"{'' if p_ok else 'PRICE'} {'' if s_ok else 'STOCK'} | truth {t['price_inr']} {t['availability']} "
                  f"| model {d.get('price_inr')} mrp={d.get('mrp_inr')} {d.get('in_stock')} {d.get('availability_text')!r} | {c['url'][:75]}")
