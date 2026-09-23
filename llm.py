"""Reply parsing with open models on Nebius Token Factory.

Cascade: the small model (Qwen3-30B-A3B, only ~3B active parameters) handles every reply first.
Only if its answer is invalid or low-confidence do we escalate to gpt-oss-120b.
"""
import json
import os
import re
import time

from openai import OpenAI

NEBIUS_BASE_URL = os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")

SMALL_MODEL = os.environ.get("SMALL_MODEL", "Qwen/Qwen3-30B-A3B-Instruct-2507")
BIG_MODEL = os.environ.get("BIG_MODEL", "openai/gpt-oss-120b")

# USD per 1M tokens (input, output) - check the model pages on Nebius and update if different
PRICES = {
    SMALL_MODEL: (0.10, 0.30),
    BIG_MODEL: (0.15, 0.60),
}

CONFIDENCE_THRESHOLD = 0.75

SYSTEM_PROMPT = """Reasoning: low

You read a short chat reply from a shift worker who was offered a shift.
The reply can be in any language (Dutch, English, Turkish, Polish, Spanish...), informal, with typos or emojis.

The offered shift runs from {start} to {end} today (24h clock). Times in replies without am/pm mean evening hours.
Dutch "half 7" means 18:30 ("half" = 30 minutes BEFORE the hour). "kwart over 5" = 17:15.

Classify the reply:
- "yes": can work the whole shift
- "no": cannot work
- "partial": can work only part of the shift (arrives later and/or leaves earlier)

Answer with ONLY a JSON object, no other text:
{{"status": "yes" | "no" | "partial",
  "from": "HH:MM" or null,
  "until": "HH:MM" or null,
  "confidence": number between 0 and 1,
  "note": short English summary (max 12 words)}}

Rules for times: for "partial" ALWAYS fill both "from" and "until" (use the shift start/end when not mentioned).
For "yes" and "no" set both to null."""

_client = None


def get_api_key():
    key = os.environ.get("NEBIUS_API_KEY")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("NEBIUS_API_KEY")
        except Exception:
            key = None
    return key


def client():
    global _client
    if _client is None:
        _client = OpenAI(base_url=NEBIUS_BASE_URL, api_key=get_api_key())
    return _client


def extract_json(text):
    """Pull the first JSON object out of model text; None if impossible."""
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def is_valid(parsed):
    if not isinstance(parsed, dict):
        return False
    if parsed.get("status") not in ("yes", "no", "partial"):
        return False
    if parsed["status"] == "partial":
        for k in ("from", "until"):
            v = parsed.get(k)
            if not isinstance(v, str) or not re.fullmatch(r"\d{2}:\d{2}", v):
                return False
    return True


def cost_usd(model, prompt_tokens, completion_tokens):
    pin, pout = PRICES[model]
    return (prompt_tokens * pin + completion_tokens * pout) / 1_000_000


def call_model(model, message, start="17:00", end="22:00"):
    """One call to one Nebius model. Returns dict with parsed result + metrics."""
    t0 = time.perf_counter()
    resp = client().chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=600,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(start=start, end=end)},
            {"role": "user", "content": message},
        ],
    )
    latency = time.perf_counter() - t0
    text = resp.choices[0].message.content or ""
    usage = resp.usage
    pt = getattr(usage, "prompt_tokens", 0) or 0
    ct = getattr(usage, "completion_tokens", 0) or 0
    parsed = extract_json(text)
    return {
        "model": model,
        "parsed": parsed if is_valid(parsed) else None,
        "raw": text,
        "latency_s": latency,
        "cost_usd": cost_usd(model, pt, ct),
        "prompt_tokens": pt,
        "completion_tokens": ct,
    }


def parse_reply(message, start="17:00", end="22:00", mode="cascade"):
    """mode: 'cascade' (small first, escalate if unsure), 'small', or 'big'."""
    if mode == "big":
        r = call_model(BIG_MODEL, message, start, end)
        r["escalated"] = False
        r["path"] = [BIG_MODEL]
        return r

    small = call_model(SMALL_MODEL, message, start, end)
    unsure = small["parsed"] is None or float(small["parsed"].get("confidence", 0)) < CONFIDENCE_THRESHOLD
    if mode == "small" or not unsure:
        small["escalated"] = False
        small["path"] = [SMALL_MODEL]
        return small

    big = call_model(BIG_MODEL, message, start, end)
    return {
        "model": BIG_MODEL,
        "parsed": big["parsed"],
        "raw": big["raw"],
        "latency_s": small["latency_s"] + big["latency_s"],
        "cost_usd": small["cost_usd"] + big["cost_usd"],
        "prompt_tokens": small["prompt_tokens"] + big["prompt_tokens"],
        "completion_tokens": small["completion_tokens"] + big["completion_tokens"],
        "escalated": True,
        "path": [SMALL_MODEL, BIG_MODEL],
    }
