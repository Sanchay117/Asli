"""Send a listing screenshot to Nemotron 3.5 Super VL and print what it reads.

Usage: python -m scripts.vl_probe <image.png>
"""
import base64
import json
import sys
import time

import requests

from asli.config import NEBIUS_API_KEY, NEBIUS_BASE_URL
from asli.listing import FIELDS

img = base64.b64encode(open(sys.argv[1], "rb").read()).decode()
for json_mode in (True, False):
    body = {"model": "nvidia/Nemotron-3.5-Super-VL", "max_tokens": 1500, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": f"This is a screenshot of an Indian e-commerce GPU listing. Return JSON with exactly these fields:\n{FIELDS}"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}}]}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    t = time.time()
    r = requests.post(f"{NEBIUS_BASE_URL}/chat/completions", headers={"Authorization": f"Bearer {NEBIUS_API_KEY}"}, json=body, timeout=180)
    print(f"json_mode={json_mode} status={r.status_code} {time.time()-t:.1f}s")
    if r.ok:
        d = r.json(); print("usage", d["usage"]); print((d["choices"][0]["message"].get("content") or "")[:900])
    else:
        print(r.text[:400])
