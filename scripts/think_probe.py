"""Check how to turn off Nemotron reasoning for cheap extraction calls.

Usage: python -m scripts.think_probe
"""
import requests

from asli.config import MODELS, NEBIUS_API_KEY, NEBIUS_BASE_URL

text = "Price Rs 58,249. Sold by: PC PARTS DEALER. Non-Returnable. " * 20
variants = {
    "default": {},
    "kwargs_off": {"chat_template_kwargs": {"enable_thinking": False}},
    "reasoning_effort_low": {"reasoning_effort": "low"},
}
for tier in ["nano", "super", "ultra"]:
    for name, extra in variants.items():
        sys_prompt = "Return JSON only."
        body = {"model": MODELS[tier]["id"], "max_tokens": 600, "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": sys_prompt},
                             {"role": "user", "content": text + "\nJSON keys: price_inr, seller, returnable"}],
                **extra}
        r = requests.post(f"{NEBIUS_BASE_URL}/chat/completions",
                          headers={"Authorization": f"Bearer {NEBIUS_API_KEY}"}, json=body, timeout=120)
        if not r.ok:
            print(tier, name, r.status_code, r.text[:150]); continue
        d = r.json(); ch = d["choices"][0]; msg = ch["message"]
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        print(f"{tier:6} {name:22} finish={ch.get('finish_reason')} out_tokens={d['usage']['completion_tokens']} "
              f"reasoning_chars={len(reasoning)} content={(msg.get('content') or '')[:80]!r}")
