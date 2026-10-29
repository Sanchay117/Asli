"""Fetch store pages directly and print schema.org Product offers (price, availability).

Usage: python -m scripts.ldjson_probe <url> [<url> ...]
"""
import json
import re
import sys

import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def walk(node):
    if isinstance(node, list):
        for n in node:
            yield from walk(n)
    elif isinstance(node, dict):
        if node.get("@type") in ("Product", ["Product"]):
            yield node
        for v in node.values():
            if isinstance(v, (dict, list)):
                yield from walk(v)


for url in sys.argv[1:]:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    except requests.RequestException as e:
        print(url, "ERR", e); continue
    print(f"\n{url}\n  status {r.status_code}, {len(r.text)} bytes")
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', r.text, re.S):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for p in walk(data):
            offers = p.get("offers")
            offers = offers if isinstance(offers, list) else [offers]
            for o in offers:
                if isinstance(o, dict):
                    print("  ", p.get("name", "")[:70], "|", o.get("price") or o.get("lowPrice"),
                          o.get("priceCurrency"), "|", o.get("availability"))
