# tests/test_openrouter_usage.py
import datetime as dt

from utils import openrouter_usage as ou


def test_parse_credits():
    payload = {"data": {"total_credits": 20.0, "total_usage": 7.5}}
    assert ou.parse_credits(payload) == {"purchased": 20.0, "used": 7.5, "balance": 12.5}


def test_clamp_dates_within_30_days():
    today = dt.date(2026, 6, 5)
    start, end, clamped = ou.clamp_dates("2026-01-01", "2026-06-05", today=today)
    assert start == dt.date(2026, 5, 6)  # 30 days back
    assert end == today
    assert clamped is True


def test_clamp_dates_already_inside_window():
    today = dt.date(2026, 6, 5)
    start, end, clamped = ou.clamp_dates("2026-06-01", "2026-06-04", today=today)
    assert (start, end, clamped) == (dt.date(2026, 6, 1), dt.date(2026, 6, 4), False)


def test_summarize_activity_totals_spend():
    rows = [
        {"date": "2026-06-04", "usage": 1.25, "requests": 10},
        {"date": "2026-06-04", "usage": 0.75, "requests": 5},
    ]
    out = ou.summarize_activity(rows, dt.date(2026, 6, 4), dt.date(2026, 6, 4), clamped=False)
    assert "$2.00" in out and "15" in out  # total spend + requests


def test_summarize_activity_notes_clamp():
    out = ou.summarize_activity([], dt.date(2026, 5, 6), dt.date(2026, 6, 5), clamped=True)
    assert "30 day" in out.lower()
