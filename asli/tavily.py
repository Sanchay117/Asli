"""Tavily search and extract, cached and metered."""
import hashlib
import json
import re
import time

import requests

from . import db
from .config import TAVILY_API_KEY, TAVILY_MONTHLY_CREDITS

API = "https://api.tavily.com"


class TavilyBudgetReached(RuntimeError):
    pass


def _key(kind, body):
    return f"tavily:{kind}:" + hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()


def _post(kind, body, credits, ttl_s):
    key = _key(kind, body)
    hit = db.cache_get(key, ttl_s)
    if hit is not None:
        return hit
    if db.spend_totals()["tavily_credits_month"] + credits > TAVILY_MONTHLY_CREDITS:
        raise TavilyBudgetReached("Monthly Tavily credit budget reached")
    t0 = time.time()
    r = requests.post(f"{API}/{kind}", headers={"Authorization": f"Bearer {TAVILY_API_KEY}"},
                      json=body, timeout=90)
    r.raise_for_status()
    data = r.json()
    db.record_spend(provider="tavily", task=kind, credits=credits, latency_s=time.time() - t0)
    db.cache_put(key, data)
    return data


def search(query, include_domains=None, max_results=5, depth="basic", ttl_s=6 * 3600):
    body = {"query": query, "max_results": max_results, "search_depth": depth}
    if include_domains:
        body["include_domains"] = include_domains
    return _post("search", body, 2 if depth == "advanced" else 1, ttl_s).get("results", [])


def extract(urls, depth="basic", ttl_s=2 * 3600):
    urls = list(urls)
    per = 2 if depth == "advanced" else 1
    credits = per * max(1, -(-len(urls) // 5))
    data = _post("extract", {"urls": urls, "extract_depth": depth}, credits, ttl_s)
    return {r["url"]: clean(r.get("raw_content") or "") for r in data.get("results", [])}


def clean(text):
    """Drop markdown images and blank lines; collapse whitespace."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\(data:[^)]*\)", "", text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(lines)
