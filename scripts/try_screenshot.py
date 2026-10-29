"""Run a full deal check from a screenshot file and print the events.

Usage: python -m scripts.try_screenshot <image.jpg> [listing_url]
"""
import base64
import sys
import time

from asli.pipeline import run_check

data = "data:image/jpeg;base64," + base64.b64encode(open(sys.argv[1], "rb").read()).decode()
t = time.time()
for ev in run_check(url=sys.argv[2] if len(sys.argv) > 2 else None, image=data):
    if ev["type"] == "step" and ev["status"] != "running":
        print(f"{time.time()-t:5.1f}s {ev['status']:5} {ev['label']}: {ev.get('summary')}")
    elif ev["type"] == "result":
        v = ev["verdict"]; l = ev["listing"]
        print("LISTING", {k: l.get(k) for k in ("title", "price_inr", "mrp_inr", "in_stock", "seller", "store")})
        print("VERDICT", v["verdict"], v["trust_score"], v["headline"], "| cost", round(ev["usage"]["cost_usd"], 4))
    elif ev["type"] != "step":
        print(ev)
