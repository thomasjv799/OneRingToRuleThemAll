"""OpenRouter balance (/credits) + spend rollups (/key).

Both endpoints work with the inference key already in OPENROUTER_API_KEY —
no separate management key needed. `/credits` gives account balance; `/key`
gives this key's today/week/month spend (the master bot is the only OpenRouter
consumer, so the key's usage tracks account usage).
"""
import logging
import os

import httpx

log = logging.getLogger("onering.openrouter_usage")

_BASE = "https://openrouter.ai/api/v1"


def _key() -> str | None:
    return os.environ.get("OPENROUTER_API_KEY")


def parse_credits(payload: dict) -> dict:
    data = payload.get("data", {})
    purchased = float(data.get("total_credits", 0))
    used = float(data.get("total_usage", 0))
    return {"purchased": purchased, "used": used, "balance": purchased - used}


def parse_key_usage(payload: dict) -> dict:
    d = payload.get("data", {})
    limit_remaining = d.get("limit_remaining")
    return {
        "today": float(d.get("usage_daily", 0)),
        "week": float(d.get("usage_weekly", 0)),
        "month": float(d.get("usage_monthly", 0)),
        "total": float(d.get("usage", 0)),
        "limit_remaining": None if limit_remaining is None else float(limit_remaining),
    }


def summarize_usage(usage: dict) -> str:
    out = (f"OpenRouter spend — today ${usage['today']:.2f}, "
           f"this week ${usage['week']:.2f}, this month ${usage['month']:.2f}.")
    if usage.get("limit_remaining") is not None:
        out += f" Key limit remaining: ${usage['limit_remaining']:.2f}."
    return out


def _headers() -> dict:
    return {"Authorization": f"Bearer {_key()}"}


def fetch_credits() -> dict:
    r = httpx.get(f"{_BASE}/credits", headers=_headers(), timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_key() -> dict:
    r = httpx.get(f"{_BASE}/key", headers=_headers(), timeout=15)
    r.raise_for_status()
    return r.json()


def key_configured() -> bool:
    return bool(_key())
