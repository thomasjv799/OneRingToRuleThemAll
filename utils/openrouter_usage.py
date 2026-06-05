# utils/openrouter_usage.py
"""OpenRouter balance (/credits) + dated usage (/activity).

Both endpoints require a *management key* (OPENROUTER_PROVISIONING_KEY),
distinct from the inference OPENROUTER_API_KEY. Activity covers the last 30
completed UTC days only.
"""
import datetime as dt
import logging
import os

import httpx

log = logging.getLogger("onering.openrouter_usage")

_BASE = "https://openrouter.ai/api/v1"
_WINDOW_DAYS = 30


def _key() -> str | None:
    return os.environ.get("OPENROUTER_PROVISIONING_KEY")


def parse_credits(payload: dict) -> dict:
    data = payload.get("data", {})
    purchased = float(data.get("total_credits", 0))
    used = float(data.get("total_usage", 0))
    return {"purchased": purchased, "used": used, "balance": purchased - used}


def clamp_dates(start: str, end: str, today: dt.date | None = None) -> tuple[dt.date, dt.date, bool]:
    today = today or dt.date.today()
    floor = today - dt.timedelta(days=_WINDOW_DAYS)
    s = dt.date.fromisoformat(start)
    e = dt.date.fromisoformat(end)
    clamped = False
    if s < floor:
        s, clamped = floor, True
    if e > today:
        e = today
    return s, e, clamped


def summarize_activity(rows: list[dict], start: dt.date, end: dt.date, clamped: bool) -> str:
    spend = sum(float(r.get("usage", 0)) for r in rows)
    requests = sum(int(r.get("requests", 0)) for r in rows)
    out = f"OpenRouter usage {start}..{end}: ${spend:.2f} across {requests} requests."
    if clamped:
        out += " (Range clamped to OpenRouter's last 30 day activity window.)"
    return out


def _headers() -> dict:
    return {"Authorization": f"Bearer {_key()}"}


def fetch_credits() -> dict:
    r = httpx.get(f"{_BASE}/credits", headers=_headers(), timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_activity(date: str | None = None) -> list[dict]:
    params = {"date": date} if date else {}
    r = httpx.get(f"{_BASE}/activity", headers=_headers(), params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("data", [])


def key_configured() -> bool:
    return bool(_key())
