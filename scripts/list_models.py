"""List models visible to the Nebius key (free call). Tries the known base URLs.

Usage: python3 scripts/list_models.py
"""
import requests

from tavily_probe import load_env

BASES = [
    "https://api.tokenfactory.nebius.com/v1",
    "https://api.studio.nebius.com/v1",
]

key = load_env()["NEBIUS_API_KEY"]
for base in BASES:
    try:
        r = requests.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    except requests.RequestException as e:
        print(base, "->", type(e).__name__)
        continue
    print(base, "->", r.status_code)
    if r.ok:
        ids = sorted(m["id"] for m in r.json().get("data", []))
        print(f"  {len(ids)} models total")
        for i in ids:
            if "nvidia" in i.lower() or "nemotron" in i.lower():
                print("  ", i)
        break
