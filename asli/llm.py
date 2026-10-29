"""Nemotron calls through Nebius Token Factory, with routing and a hard spend cap."""
import json
import re
import time

import requests

from . import db
from .config import (BILLING_FACTOR, DATA_DIR, DEFAULT_ROUTING, MODELS, MONTHLY_CAP_USD,
                     NEBIUS_API_KEY, NEBIUS_BASE_URL, SPEND_CAP_USD)

ROUTING_FILE = DATA_DIR / "routing.json"


class SpendCapReached(RuntimeError):
    pass


def routing():
    table = dict(DEFAULT_ROUTING)
    if ROUTING_FILE.exists():
        table.update(json.loads(ROUTING_FILE.read_text()).get("routing", {}))
    return table


def thinking(task, default):
    """Whether a task runs with Nemotron reasoning on, as chosen by the eval."""
    if ROUTING_FILE.exists():
        return json.loads(ROUTING_FILE.read_text()).get("thinking", {}).get(task, default)
    return default


def cost_of(tier, prompt_tokens, completion_tokens):
    p_in, p_out = MODELS[tier]["price"]
    return BILLING_FACTOR * (prompt_tokens * p_in + completion_tokens * p_out) / 1_000_000


def check_budget():
    totals = db.spend_totals()
    if totals["total_usd"] >= SPEND_CAP_USD:
        raise SpendCapReached(f"Total spend cap ${SPEND_CAP_USD} reached")
    if totals["month_usd"] >= MONTHLY_CAP_USD:
        raise SpendCapReached(f"Monthly spend cap ${MONTHLY_CAP_USD} reached")


def parse_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def _post(body, label):
    last_err = None
    for attempt in range(3):
        try:
            r = requests.post(f"{NEBIUS_BASE_URL}/chat/completions",
                              headers={"Authorization": f"Bearer {NEBIUS_API_KEY}"},
                              json=body, timeout=180)
            if r.status_code in (429, 500, 502, 503, 504):
                last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{label} call failed: {last_err}")


def chat_json(task, system, user, tier=None, max_tokens=2000, temperature=0, think=False,
              image=None):
    """Run one JSON task. Returns (parsed, meta) where meta has model, tokens, cost.

    image is an optional data URL sent alongside the user text (vision model only).

    think=False turns off Nemotron reasoning, which cuts output tokens about 7x
    on extraction tasks with the same answers.
    """
    check_budget()
    tier = tier or routing().get(task, "nano")
    model = MODELS[tier]
    body = {
        "model": model["id"],
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user if not image else [
                         {"type": "text", "text": user},
                         {"type": "image_url", "image_url": {"url": image}}]}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": think},
    }
    if tier == "vision":
        # The VL endpoint hangs on images with chat_template_kwargs or JSON mode; a
        # "/no_think" system message turns reasoning off instead (90s -> about 10s).
        body["messages"] = [{"role": "system", "content": "/no_think"},
                            {"role": "user", "content": [
                                {"type": "image_url", "image_url": {"url": image}},
                                {"type": "text", "text": f"{system}\n\n{user}"}]}]
        body.pop("chat_template_kwargs")
        body.pop("response_format")
    t0 = time.time()
    pt = ct = 0
    parsed = None
    # Super with JSON mode and reasoning off either loops on escaped JSON until the token
    # limit or returns {}, so a failed or empty parse retries once without JSON mode.
    for json_mode in (True, False):
        if not json_mode:
            body.pop("response_format", None)
        data = _post(body, model["label"])
        usage = data.get("usage") or {}
        pt += usage.get("prompt_tokens", 0)
        ct += usage.get("completion_tokens", 0)
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            continue
        try:
            parsed = parse_json(choice["message"].get("content"))
            if parsed:
                break
            parsed = None  # an empty {} is a failure too
        except (json.JSONDecodeError, TypeError):
            continue
    latency = time.time() - t0
    cost = cost_of(tier, pt, ct)
    db.record_spend(provider="nebius", model=tier, task=task, prompt_tokens=pt,
                    completion_tokens=ct, cost_usd=cost, latency_s=latency)
    if parsed is None:
        raise ValueError(f"{model['label']} returned unreadable output on {task}")
    meta = {"tier": tier, "think": think, "model": model["label"], "model_id": model["id"],
            "prompt_tokens": pt, "completion_tokens": ct, "cost_usd": cost,
            "latency_s": round(latency, 2)}
    return parsed, meta
