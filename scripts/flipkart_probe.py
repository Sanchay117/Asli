"""Probe two Flipkart workarounds: Tavily search snippets, and a direct page fetch.

Usage: python3 scripts/flipkart_probe.py <flipkart_url> <out_dir>
"""
import json
import re
import sys
from pathlib import Path

import requests

from tavily_probe import load_env, post

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def main():
    url, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    key = load_env()["TAVILY_API_KEY"]

    print("== A: Tavily search with raw content ==")
    res = post("search", key, {
        "query": "GIGABYTE RTX 3060 WINDFORCE OC 12GD flipkart price seller",
        "include_domains": ["flipkart.com"],
        "max_results": 3,
        "include_raw_content": True,
    })
    for r in res.get("results", []):
        snippet = r.get("content", "")
        raw = r.get("raw_content") or ""
        print(r["url"][:100])
        print("  snippet:", snippet[:300].replace("\n", " "))
        print("  raw prices:", re.findall(r"₹\s?[\d,]{4,}", raw)[:5])

    print("\n== B: direct fetch ==")
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-IN"}, timeout=30)
    html = r.text
    (out / "flipkart.html").write_text(html)
    print("status", r.status_code, "bytes", len(html))
    print("prices:", re.findall(r"₹\s?[\d,]{4,}", html)[:8])
    for word in ["Sold Out", "Coming Soon", "Notify Me", "Currently Unavailable",
                 "BUY NOW", "ADD TO CART", "Seller", "sellerName"]:
        print(f"  {word!r}: {html.count(word)}")
    m = re.search(r'"sellerName"\s*:\s*"([^"]+)"', html)
    print("sellerName json:", m.group(1) if m else None)


if __name__ == "__main__":
    main()
