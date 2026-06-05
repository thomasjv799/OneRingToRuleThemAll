# tests/test_openrouter_usage.py
from utils import openrouter_usage as ou


def test_parse_credits():
    payload = {"data": {"total_credits": 20.0, "total_usage": 7.5}}
    assert ou.parse_credits(payload) == {"purchased": 20.0, "used": 7.5, "balance": 12.5}


def test_parse_key_usage():
    payload = {"data": {
        "usage_daily": 0.25, "usage_weekly": 1.5, "usage_monthly": 4.0,
        "usage": 9.0, "limit_remaining": 2.98,
    }}
    assert ou.parse_key_usage(payload) == {
        "today": 0.25, "week": 1.5, "month": 4.0, "total": 9.0, "limit_remaining": 2.98,
    }


def test_parse_key_usage_null_limit():
    payload = {"data": {"usage_daily": 0.1, "usage_weekly": 0.2, "usage_monthly": 0.3,
                        "usage": 0.3, "limit_remaining": None}}
    assert ou.parse_key_usage(payload)["limit_remaining"] is None


def test_summarize_usage_reports_buckets():
    out = ou.summarize_usage({"today": 0.25, "week": 1.5, "month": 4.0,
                              "total": 9.0, "limit_remaining": 2.98})
    assert "today $0.25" in out and "this week $1.50" in out and "this month $4.00" in out
    assert "remaining: $2.98" in out


def test_summarize_usage_omits_limit_when_none():
    out = ou.summarize_usage({"today": 0.0, "week": 0.0, "month": 0.0,
                              "total": 0.0, "limit_remaining": None})
    assert "remaining" not in out
