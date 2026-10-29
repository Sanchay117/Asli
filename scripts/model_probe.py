"""Tiny call to each Nemotron model to see response shape, usage and JSON behaviour.

Usage: python3 scripts/model_probe.py
"""
import json
import time

import requests

from tavily_probe import load_env

BASE = "https://api.tokenfactory.nebius.com/v1"
MODELS = [
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/Nemotron-3-Ultra-550b-a55b",
]

key = load_env()["NEBIUS_API_KEY"]
prompt = ('Listing text: "MSI RTX 3060 12GB, price Rs 28,839, MRP 86,000, Notify Me". '
          'Return JSON with keys price_inr (int), mrp_inr (int), in_stock (bool). JSON only.')

for model in MODELS:
    t = time.time()
    r = requests.post(f"{BASE}/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 800,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }, timeout=180)
    print(f"\n== {model}  status={r.status_code}  {time.time() - t:.1f}s")
    if not r.ok:
        print(r.text[:500])
        continue
    data = r.json()
    msg = data["choices"][0]["message"]
    print("keys:", list(msg.keys()))
    print("content:", (msg.get("content") or "")[:400])
    if msg.get("reasoning_content"):
        print("reasoning_content chars:", len(msg["reasoning_content"]))
    print("usage:", json.dumps(data.get("usage")))
