# Server Metrics, Container Health & OpenRouter Cost — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 8 read-only OneRing tools for Prometheus/Loki metrics+logs, Docker-socket container health, and OpenRouter balance/usage.

**Architecture:** Three new `utils/` modules with a thin HTTP fetch layer wrapping **pure parse/format functions** (so logic is unit-testable without network or daemon). Tools are wired into the existing `bot/functions.py` `TOOLS` + `_FUNCTION_MAP` + `dispatch()` pattern, each returning a concise formatted string.

**Tech Stack:** Python, httpx (existing dep), pytest, Prometheus/Loki HTTP APIs, Docker Engine API over a Unix socket.

**Design doc:** `docs/superpowers/specs/2026-06-05-onering-metrics-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `utils/metrics.py` (create) | Prometheus instant/range + Loki query: HTTP fetch + pure parsers + range summary + canned PromQL map |
| `utils/docker_status.py` (create) | Docker Engine API over socket: fetch + health classification + container summary |
| `utils/openrouter_usage.py` (create) | OpenRouter `/credits` + `/activity`: fetch + parse + 30-day clamp + summary |
| `bot/functions.py` (modify) | 8 new tool functions, schemas appended to `TOOLS`, entries in `_FUNCTION_MAP` |
| `ai/graph.py` (modify) | Extend `SYSTEM_PROMPT` with the monitoring capability bullet |
| `docker-compose.yml` (modify) | Add `extra_hosts` + `docker.sock` volume |
| `.env.example` (modify) | Add `PROMETHEUS_URL`, `LOKI_URL`, `OPENROUTER_PROVISIONING_KEY` |
| `tests/test_metrics.py` (create) | Parser + summary + canned-map tests |
| `tests/test_docker_status.py` (create) | Health classification + summary tests |
| `tests/test_openrouter_usage.py` (create) | Credits/activity parse + clamp tests |

Run tests with: `python -m pytest tests/ -v` (from repo root, inside the project venv/container).

---

## Task 1: Prometheus/Loki parsers (`utils/metrics.py`)

**Files:**
- Create: `utils/metrics.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write failing tests for the pure parsers + canned map**

```python
# tests/test_metrics.py
from utils import metrics


def test_parse_instant_returns_metric_value_pairs():
    payload = {"data": {"resultType": "vector", "result": [
        {"metric": {"__name__": "x"}, "value": [1700000000, "42.5"]},
    ]}}
    assert metrics.parse_instant(payload) == [({"__name__": "x"}, 42.5)]


def test_parse_instant_empty():
    assert metrics.parse_instant({"data": {"result": []}}) == []


def test_parse_range_returns_series():
    payload = {"data": {"result": [
        {"metric": {}, "values": [[1, "10"], [2, "20"], [3, "15"]]},
    ]}}
    series = metrics.parse_range(payload)
    assert series == [({}, [(1.0, 10.0), (2.0, 20.0), (3.0, 15.0)])]


def test_summarize_range_reports_min_max_avg_latest():
    out = metrics.summarize_range("cpu_percent", [(1.0, 10.0), (2.0, 20.0), (3.0, 15.0)])
    assert "min 10" in out and "max 20" in out and "latest 15" in out


def test_summarize_range_no_data():
    assert "no data" in metrics.summarize_range("cpu_percent", []).lower()


def test_parse_loki_returns_ts_line_pairs():
    payload = {"data": {"result": [
        {"stream": {"container": "c"}, "values": [["1700000000000000000", "boom"]]},
    ]}}
    assert metrics.parse_loki(payload) == [("1700000000000000000", "boom")]


def test_canned_map_has_core_metrics():
    for name in ("cpu_percent", "ram_percent", "disk_percent", "cpu_temp"):
        assert name in metrics.CANNED
        assert metrics.CANNED[name]  # non-empty PromQL
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: utils.metrics` / attribute errors.

- [ ] **Step 3: Implement the module (parsers + canned map; HTTP wrappers added next task)**

```python
# utils/metrics.py
"""Prometheus (metrics) + Loki (logs) HTTP access for OneRing tools.

Logic is split into pure parse/format functions (unit-tested) and thin httpx
fetch wrappers (Task 2). Prometheus and Loki are unauthenticated on the LAN.
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_metrics.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add utils/metrics.py tests/test_metrics.py
git commit -m "feat: prometheus/loki parsers + canned metric map"
```

---

## Task 2: Prometheus/Loki HTTP fetch + high-level helpers (`utils/metrics.py`)

**Files:**
- Modify: `utils/metrics.py`

- [ ] **Step 1: Add fetch wrappers and the helpers the tools will call**

Append to `utils/metrics.py`:

```python
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
```

- [ ] **Step 2: Add a test for `_duration_seconds` (pure, no network)**

Add to `tests/test_metrics.py`:

```python
import pytest


@pytest.mark.parametrize("text,expected", [
    ("30s", 30), ("5m", 300), ("2h", 7200), ("1d", 86400), ("45", 45),
])
def test_duration_seconds(text, expected):
    assert metrics._duration_seconds(text) == expected
```

- [ ] **Step 3: Run tests to verify pass**

Run: `python -m pytest tests/test_metrics.py -v`
Expected: PASS (all, including the 5 parametrized duration cases).

- [ ] **Step 4: Commit**

```bash
git add utils/metrics.py tests/test_metrics.py
git commit -m "feat: prometheus/loki http fetch helpers"
```

---

## Task 3: Docker socket status (`utils/docker_status.py`)

**Files:**
- Create: `utils/docker_status.py`
- Test: `tests/test_docker_status.py`

- [ ] **Step 1: Write failing tests for health classification + summary (pure functions)**

```python
# tests/test_docker_status.py
from utils import docker_status as ds


def test_classify_health_variants():
    assert ds.classify_health("Up 2 hours (healthy)") == "healthy"
    assert ds.classify_health("Up 5 minutes (unhealthy)") == "unhealthy"
    assert ds.classify_health("Up 3 seconds (health: starting)") == "starting"
    assert ds.classify_health("Up 4 days") == "none"
    assert ds.classify_health("Exited (1) 2 minutes ago") == "none"


def test_summarize_counts_and_unhealthy():
    containers = [
        {"Names": ["/onering-bot"], "State": "running", "Status": "Up 1 day (healthy)", "RestartCount": 0},
        {"Names": ["/gs-loki"], "State": "running", "Status": "Up 2h (unhealthy)", "RestartCount": 3},
        {"Names": ["/old-job"], "State": "exited", "Status": "Exited (0) 1h ago", "RestartCount": 0},
    ]
    out = ds.summarize_containers(containers)
    assert "3 total" in out
    assert "2 running" in out
    assert "1 stopped" in out
    assert "1 unhealthy" in out
    assert "gs-loki" in out  # unhealthy container named


def test_summarize_filter_by_name():
    containers = [
        {"Names": ["/onering-bot"], "State": "running", "Status": "Up 1d (healthy)", "RestartCount": 0},
        {"Names": ["/gs-loki"], "State": "running", "Status": "Up 2h", "RestartCount": 0},
    ]
    out = ds.summarize_containers(containers, name="onering")
    assert "onering-bot" in out and "gs-loki" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_docker_status.py -v`
Expected: FAIL with `ModuleNotFoundError: utils.docker_status`.

- [ ] **Step 3: Implement the module**

```python
# utils/docker_status.py
"""Container state + health via the Docker Engine API over the mounted socket.

Read-only: lists containers and classifies health. No create/exec/stop.
"""
import logging

import httpx

log = logging.getLogger("onering.docker_status")

DOCKER_SOCK = "/var/run/docker.sock"


def classify_health(status: str) -> str:
    s = status.lower()
    if "(healthy)" in s:
        return "healthy"
    if "(unhealthy)" in s:
        return "unhealthy"
    if "health: starting" in s:
        return "starting"
    return "none"


def _name(container: dict) -> str:
    names = container.get("Names") or ["?"]
    return names[0].lstrip("/")


def summarize_containers(containers: list[dict], name: str | None = None) -> str:
    if name:
        containers = [c for c in containers if name.lower() in _name(c).lower()]
        if not containers:
            return f"No container matching '{name}'."

    total = len(containers)
    running = sum(1 for c in containers if c.get("State") == "running")
    stopped = total - running
    unhealthy = [c for c in containers if classify_health(c.get("Status", "")) == "unhealthy"]

    header = f"{total} total, {running} running, {stopped} stopped, {len(unhealthy)} unhealthy"
    lines = [header]
    for c in containers:
        health = classify_health(c.get("Status", ""))
        tag = "" if health == "none" else f" [{health}]"
        restarts = c.get("RestartCount", 0)
        rst = f", restarts {restarts}" if restarts else ""
        lines.append(f"  {_name(c)}: {c.get('State')}{tag}{rst}")
    return "\n".join(lines)


def fetch_containers() -> list[dict]:
    transport = httpx.HTTPTransport(uds=DOCKER_SOCK)
    with httpx.Client(transport=transport, timeout=10) as client:
        r = client.get("http://localhost/containers/json?all=1")
        r.raise_for_status()
        return r.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_docker_status.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add utils/docker_status.py tests/test_docker_status.py
git commit -m "feat: docker socket container health status"
```

---

## Task 4: OpenRouter usage (`utils/openrouter_usage.py`)

**Files:**
- Create: `utils/openrouter_usage.py`
- Test: `tests/test_openrouter_usage.py`

- [ ] **Step 1: Write failing tests for parse + clamp + summaries (pure functions)**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_openrouter_usage.py -v`
Expected: FAIL with `ModuleNotFoundError: utils.openrouter_usage`.

- [ ] **Step 3: Implement the module**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_openrouter_usage.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add utils/openrouter_usage.py tests/test_openrouter_usage.py
git commit -m "feat: openrouter balance + activity usage helpers"
```

---

## Task 5: Tool functions in `bot/functions.py`

**Files:**
- Modify: `bot/functions.py`

- [ ] **Step 1: Add imports and the 8 tool functions**

Add near the top of `bot/functions.py` (after existing imports):

```python
from utils import docker_status, metrics, openrouter_usage
```

Add a new section before the `TOOLS = [` definition:

```python
# ---------------------------------------------------------------------------
# Monitoring functions (Prometheus / Loki / Docker)
# ---------------------------------------------------------------------------

_HEALTH_METRICS = [("CPU", "cpu_percent", "%"), ("RAM", "ram_percent", "%"),
                   ("Disk", "disk_percent", "%"), ("Temp", "cpu_temp", "°C")]


def get_system_health(user_id: str) -> str:
    parts = []
    for label, name, unit in _HEALTH_METRICS:
        try:
            val = metrics.canned_value(name)
            parts.append(f"{label}: {val:.1f}{unit}" if val is not None else f"{label}: n/a")
        except Exception as exc:
            logger.error("metric %s failed: %s", name, exc)
            parts.append(f"{label}: error")
    return "Server health — " + ", ".join(parts)


def get_metric_range(user_id: str, metric: str, duration: str = "1h") -> str:
    if metric not in metrics.CANNED:
        return f"Unknown metric '{metric}'. Known: {', '.join(metrics.CANNED)}."
    try:
        series = metrics.range_query(metrics.CANNED[metric], duration=duration)
    except Exception as exc:
        return f"Prometheus is unreachable ({exc})."
    points = series[0][1] if series else []
    return metrics.summarize_range(f"{metric} over {duration}", points)


def get_container_status(user_id: str, name: str = None) -> str:
    try:
        containers = docker_status.fetch_containers()
    except Exception as exc:
        return f"Docker status unavailable (socket not mounted? {exc})."
    return docker_status.summarize_containers(containers, name=name)


def search_logs(user_id: str, container: str, level: str = None, duration: str = "1h") -> str:
    selector = '{container="%s"}' % container
    if level:
        selector += ' |~ "(?i)%s"' % level
    try:
        rows = metrics.loki_query(selector, duration=duration, limit=30)
    except Exception as exc:
        return f"Loki is unreachable ({exc})."
    if not rows:
        return f"No logs for {container} in the last {duration}."
    lines = [line for _, line in rows][:30]
    return f"Last {len(lines)} log lines for {container}:\n" + "\n".join(lines)


def query_prometheus(user_id: str, promql: str, range: str = None) -> str:
    try:
        if range:
            series = metrics.range_query(promql, duration=range)
            points = series[0][1] if series else []
            return metrics.summarize_range(f"query over {range}", points)
        rows = metrics.instant(promql)
    except Exception as exc:
        return f"Prometheus query failed ({exc})."
    if not rows:
        return "Query returned no data."
    return "\n".join(f"{m or 'value'}: {v:.3f}" for m, v in rows[:20])


def query_loki(user_id: str, logql: str, duration: str = "1h") -> str:
    try:
        rows = metrics.loki_query(logql, duration=duration, limit=30)
    except Exception as exc:
        return f"Loki query failed ({exc})."
    if not rows:
        return "Query returned no log lines."
    return "\n".join(line for _, line in rows[:30])


def get_openrouter_balance(user_id: str) -> str:
    if not openrouter_usage.key_configured():
        return "OpenRouter cost tracking not configured — add OPENROUTER_PROVISIONING_KEY to .env."
    try:
        info = openrouter_usage.parse_credits(openrouter_usage.fetch_credits())
    except Exception as exc:
        return f"Could not fetch OpenRouter balance ({exc})."
    return (f"OpenRouter balance: ${info['balance']:.2f} "
            f"(purchased ${info['purchased']:.2f}, used ${info['used']:.2f}).")


def get_openrouter_usage(user_id: str, start_date: str = None, end_date: str = None) -> str:
    import datetime as _dt

    if not openrouter_usage.key_configured():
        return "OpenRouter cost tracking not configured — add OPENROUTER_PROVISIONING_KEY to .env."
    today = _dt.date.today()
    start_date = start_date or (today - _dt.timedelta(days=_dt.date.resolution.days * 0 + 30)).isoformat()
    end_date = end_date or today.isoformat()
    start, end, clamped = openrouter_usage.clamp_dates(start_date, end_date, today=today)
    rows = []
    try:
        day = start
        while day <= end:
            rows.extend(openrouter_usage.fetch_activity(date=day.isoformat()))
            day += _dt.timedelta(days=1)
    except Exception as exc:
        return f"Could not fetch OpenRouter usage ({exc})."
    return openrouter_usage.summarize_activity(rows, start, end, clamped)
```

> Note: the `start_date` default above resolves to 30 days ago. If you prefer clarity, replace the `start_date = start_date or ...` line with:
> `start_date = start_date or (today - _dt.timedelta(days=30)).isoformat()`

- [ ] **Step 2: Use the simpler 30-day default**

Replace the convoluted default line in `get_openrouter_usage` with the clear version:

```python
    start_date = start_date or (today - _dt.timedelta(days=30)).isoformat()
```

- [ ] **Step 3: Append the 8 tool schemas to `TOOLS`**

Add these entries inside the `TOOLS = [ ... ]` list (before the closing `]`):

```python
    {"type": "function", "function": {
        "name": "get_system_health",
        "description": "Current server health snapshot: CPU %, RAM %, disk %, and CPU temperature.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "get_metric_range",
        "description": "A system metric over a time window, summarized as min/max/avg/latest.",
        "parameters": {"type": "object", "properties": {
            "metric": {"type": "string", "enum": ["cpu_percent", "ram_percent", "disk_percent", "cpu_temp"]},
            "duration": {"type": "string", "description": "e.g. 1h, 24h, 7d (default 1h)"}},
            "required": ["metric"]}}},
    {"type": "function", "function": {
        "name": "get_container_status",
        "description": "Docker container status: total/running/stopped/unhealthy counts and per-container health. Optionally filter by name.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "Optional container name substring."}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "search_logs",
        "description": "Search a container's recent logs via Loki. Optional level filter (e.g. error).",
        "parameters": {"type": "object", "properties": {
            "container": {"type": "string", "description": "Container name."},
            "level": {"type": "string", "description": "Optional case-insensitive match (e.g. error, warn)."},
            "duration": {"type": "string", "description": "Lookback, e.g. 1h, 6h (default 1h)."}},
            "required": ["container"]}}},
    {"type": "function", "function": {
        "name": "query_prometheus",
        "description": "Run a raw PromQL query (escape hatch). Pass range like 6h for a range query.",
        "parameters": {"type": "object", "properties": {
            "promql": {"type": "string", "description": "Raw PromQL expression."},
            "range": {"type": "string", "description": "Optional window for a range query, e.g. 6h."}},
            "required": ["promql"]}}},
    {"type": "function", "function": {
        "name": "query_loki",
        "description": "Run a raw LogQL query against Loki (escape hatch).",
        "parameters": {"type": "object", "properties": {
            "logql": {"type": "string", "description": "Raw LogQL expression."},
            "duration": {"type": "string", "description": "Lookback window, e.g. 1h (default 1h)."}},
            "required": ["logql"]}}},
    {"type": "function", "function": {
        "name": "get_openrouter_balance",
        "description": "Current OpenRouter credit balance and lifetime purchased/used amounts.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "get_openrouter_usage",
        "description": "OpenRouter spend over a date range (YYYY-MM-DD). Limited to the last 30 days.",
        "parameters": {"type": "object", "properties": {
            "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default 30 days ago)."},
            "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default today)."}},
            "required": []}}},
```

- [ ] **Step 4: Register the 8 functions in `_FUNCTION_MAP`**

Add these entries to the `_FUNCTION_MAP` dict:

```python
    "get_system_health": get_system_health,
    "get_metric_range": get_metric_range,
    "get_container_status": get_container_status,
    "search_logs": search_logs,
    "query_prometheus": query_prometheus,
    "query_loki": query_loki,
    "get_openrouter_balance": get_openrouter_balance,
    "get_openrouter_usage": get_openrouter_usage,
```

- [ ] **Step 5: Verify the module imports and every tool is wired**

Run:

```bash
python -c "from bot.functions import TOOLS, _FUNCTION_MAP; names={t['function']['name'] for t in TOOLS}; req={'get_system_health','get_metric_range','get_container_status','search_logs','query_prometheus','query_loki','get_openrouter_balance','get_openrouter_usage'}; assert req<=names, req-names; assert req<=set(_FUNCTION_MAP), req-set(_FUNCTION_MAP); print('OK', len(TOOLS), 'tools')"
```

Expected: `OK 24 tools` (16 existing + 8 new; exact count may differ — the assertions are what matter).

- [ ] **Step 6: Commit**

```bash
git add bot/functions.py
git commit -m "feat: wire 8 monitoring + openrouter tools into the agent"
```

---

## Task 6: System prompt, compose, and env config

**Files:**
- Modify: `ai/graph.py`
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Extend `SYSTEM_PROMPT` in `ai/graph.py`**

In the `SYSTEM_PROMPT` string, add this bullet before the final "When updating a vehicle..." sentence:

```python
    "- Monitor the home server: current health (CPU/RAM/disk/temp), metric trends "
    "over time, Docker container status and health, and container logs. Prefer the "
    "named helpers (get_system_health, get_metric_range, get_container_status, "
    "search_logs); use query_prometheus/query_loki only for unusual questions.\n"
    "- Report OpenRouter cost: current balance and spend over a date range "
    "(get_openrouter_balance, get_openrouter_usage).\n"
```

- [ ] **Step 2: Add socket mount + host gateway to `docker-compose.yml`**

Under the `onering` service, add `extra_hosts` and `volumes` (keep existing `networks`):

```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
```

- [ ] **Step 3: Add config keys to `.env.example`**

Append:

```
# Monitoring (Prometheus + Loki, published on the host)
PROMETHEUS_URL=http://host.docker.internal:9090
LOKI_URL=http://host.docker.internal:3100

# OpenRouter management key for balance/usage (distinct from OPENROUTER_API_KEY)
OPENROUTER_PROVISIONING_KEY=
```

- [ ] **Step 4: Verify compose is valid**

Run: `docker compose config >/dev/null && echo OK`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add ai/graph.py docker-compose.yml .env.example
git commit -m "feat: system prompt + compose socket/host config for monitoring"
```

---

## Task 7: Full test run + push

**Files:** none (verification)

- [ ] **Step 1: Run the whole suite**

Run: `python -m pytest tests/ -v`
Expected: all tests PASS (metrics, docker_status, openrouter_usage).

- [ ] **Step 2: Import smoke test**

Run: `python -c "import bot.functions, ai.graph; print('imports OK')"`
Expected: `imports OK`

- [ ] **Step 3: Push the branch**

```bash
git push -u origin feat/metrics-observability
```

- [ ] **Step 4: (Manual, post-merge) Go live**

Documented in the spec's "Required user actions": create the OpenRouter management key, set env vars, then `docker compose up --build -d`. Verify in-container with a real question ("how's the server doing?", "any unhealthy containers?", "what's my openrouter balance?").

---

## Self-Review Notes

- **Spec coverage:** system health (T1/T5), trends (T2/T5), container health incl. unhealthy via socket (T3/T5), Loki logs (T1/T2/T5), raw escape hatches (T5), OpenRouter balance + 30-day usage with clamp + unset-key path (T4/T5), networking/socket/env (T6), tests per module (T1–T4), system prompt (T6). All covered.
- **No placeholders:** every code step shows full code; commands have expected output.
- **Type consistency:** `metrics.CANNED`, `metrics.instant/range_query/loki_query/canned_value/summarize_range`, `docker_status.fetch_containers/summarize_containers/classify_health`, `openrouter_usage.parse_credits/clamp_dates/summarize_activity/fetch_credits/fetch_activity/key_configured` — names referenced in `bot/functions.py` (T5) match their definitions (T1–T4).
