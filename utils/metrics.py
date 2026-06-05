"""Prometheus (metrics) + Loki (logs) HTTP access for OneRing tools.

Logic is split into pure parse/format functions (unit-tested) and thin httpx
fetch wrappers (added in a later task). Prometheus and Loki are unauthenticated
on the LAN.
"""
import logging
import os

import httpx

log = logging.getLogger("onering.metrics")

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://host.docker.internal:9090")
LOKI_URL = os.environ.get("LOKI_URL", "http://host.docker.internal:3100")

CANNED: dict[str, str] = {
    "cpu_percent": '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)',
    "ram_percent": "(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100",
    "disk_percent": (
        '(1 - node_filesystem_avail_bytes{mountpoint="/",fstype!="tmpfs"} '
        '/ node_filesystem_size_bytes{mountpoint="/",fstype!="tmpfs"}) * 100'
    ),
    "cpu_temp": "max(node_hwmon_temp_celsius)",
}


def parse_instant(payload: dict) -> list[tuple[dict, float]]:
    out = []
    for item in payload.get("data", {}).get("result", []):
        out.append((item.get("metric", {}), float(item["value"][1])))
    return out


def parse_range(payload: dict) -> list[tuple[dict, list[tuple[float, float]]]]:
    out = []
    for item in payload.get("data", {}).get("result", []):
        pts = [(float(ts), float(val)) for ts, val in item.get("values", [])]
        out.append((item.get("metric", {}), pts))
    return out


def parse_loki(payload: dict) -> list[tuple[str, str]]:
    out = []
    for stream in payload.get("data", {}).get("result", []):
        for ts, line in stream.get("values", []):
            out.append((ts, line))
    return out


def summarize_range(name: str, points: list[tuple[float, float]]) -> str:
    if not points:
        return f"{name}: no data in window."
    vals = [v for _, v in points]
    latest = vals[-1]
    return (
        f"{name}: min {min(vals):.1f}, max {max(vals):.1f}, "
        f"avg {sum(vals) / len(vals):.1f}, latest {latest:.1f}"
    )


_TIMEOUT = 15


def _get(url: str, params: dict) -> dict:
    r = httpx.get(url, params=params, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def instant(promql: str) -> list[tuple[dict, float]]:
    return parse_instant(_get(f"{PROMETHEUS_URL}/api/v1/query", {"query": promql}))


def range_query(promql: str, duration: str = "1h", step: str = "60s") -> list[tuple[dict, list[tuple[float, float]]]]:
    import time

    end = int(time.time())
    start = end - _duration_seconds(duration)
    payload = _get(
        f"{PROMETHEUS_URL}/api/v1/query_range",
        {"query": promql, "start": start, "end": end, "step": step},
    )
    return parse_range(payload)


def loki_query(logql: str, duration: str = "1h", limit: int = 50) -> list[tuple[str, str]]:
    import time

    end_ns = int(time.time() * 1e9)
    start_ns = end_ns - _duration_seconds(duration) * 1_000_000_000
    payload = _get(
        f"{LOKI_URL}/loki/api/v1/query_range",
        {"query": logql, "start": start_ns, "end": end_ns, "limit": limit, "direction": "backward"},
    )
    return parse_loki(payload)


def canned_value(name: str) -> float | None:
    """Single scalar value for a canned metric, or None if no data."""
    rows = instant(CANNED[name])
    return rows[0][1] if rows else None


_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _duration_seconds(text: str) -> int:
    text = text.strip().lower()
    unit = text[-1]
    if unit in _UNITS:
        return int(float(text[:-1]) * _UNITS[unit])
    return int(float(text))  # bare seconds
