"""Probe: can Tavily find and read GPU listings on Indian stores?

Usage: python3 scripts/tavily_probe.py <out_dir>
Writes raw extract output per URL to <out_dir> and prints a summary.
"""
import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.tavily.com"

STORES = [
    "flipkart.com",
    "amazon.in",
    "mdcomputers.in",
    "primeabgb.com",
    "vedantcomputers.com",
    "elitehubs.com",
]

STOCK_WORDS = [
    "out of stock", "in stock", "notify me", "currently unavailable",
    "add to cart", "buy now", "sold out", "coming soon",
]


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def post(path, key, body):
    r = requests.post(
        f"{API}/{path}",
        headers={"Authorization": f"Bearer {key}"},
        json=body,
        timeout=90,
    )
    r.raise_for_status()
    return r.json()


def summarize(text):
    low = text.lower()
    prices = re.findall(r"(?:₹|rs\.?|inr)\s?[\d,]{4,}", text, flags=re.I)
    return {
        "chars": len(text),
        "prices": prices[:5],
        "stock_words": [w for w in STOCK_WORDS if w in low],
        "mentions_3060": "3060" in low,
        "seller_hint": bool(re.search(r"sold by|seller|retailer", low)),
    }


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    key = load_env()["TAVILY_API_KEY"]

    urls = {}
    for store in STORES:
        res = post("search", key, {
            "query": "RTX 3060 12GB graphics card price",
            "include_domains": [store],
            "max_results": 3,
        })
        urls[store] = [r["url"] for r in res.get("results", [])]
        print(f"[search] {store}: {len(urls[store])} urls")
        for u in urls[store]:
            print("   ", u)

    report = {}
    for depth in ["basic", "advanced"]:
        for store, us in urls.items():
            if not us:
                continue
            target = us[:2]
            res = post("extract", key, {"urls": target, "extract_depth": depth})
            for r in res.get("results", []):
                text = r.get("raw_content") or ""
                name = re.sub(r"\W+", "_", r["url"])[:120]
                (out / f"{depth}__{name}.txt").write_text(text)
                report.setdefault(store, []).append(
                    {"depth": depth, "url": r["url"], **summarize(text)})
            for f in res.get("failed_results", []):
                report.setdefault(store, []).append(
                    {"depth": depth, "url": f.get("url"), "failed": f.get("error")})

    (out / "report.json").write_text(json.dumps({"urls": urls, "report": report}, indent=2))
    print("\n=== extract summary ===")
    for store, rows in report.items():
        print(f"\n{store}")
        for row in rows:
            if "failed" in row:
                print(f"  [{row['depth']}] FAILED {row['url']}: {row['failed']}")
            else:
                print(f"  [{row['depth']}] {row['chars']} chars, prices={row['prices'][:3]}, "
                      f"stock={row['stock_words']}, seller={row['seller_hint']}  {row['url'][:90]}")


if __name__ == "__main__":
    main()
