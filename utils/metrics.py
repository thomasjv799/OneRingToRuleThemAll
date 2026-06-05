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
