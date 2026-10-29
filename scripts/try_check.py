"""Run a full deal check from the command line and print events.

Usage: python -m scripts.try_check <url>
"""
import json
import sys

from asli.pipeline import run_check

for ev in run_check(sys.argv[1]):
    if ev["type"] == "step":
        calls = ", ".join(f"{c['model']} {c['prompt_tokens']}+{c['completion_tokens']}tok "
                          f"${c['cost_usd']:.5f} {c['latency_s']}s" for c in ev.get("calls", []))
        print(f"[{ev['status']:7}] {ev['label']}: {ev.get('summary', '')}  {calls}")
    elif ev["type"] == "result":
        print(json.dumps(ev["verdict"], indent=1, ensure_ascii=False))
        print("market offers:", json.dumps(ev["market"]["offers"][:6], ensure_ascii=False)[:1500])
        print("signals:", ev["signals"])
        print("usage:", ev["usage"])
    else:
        print(ev)
