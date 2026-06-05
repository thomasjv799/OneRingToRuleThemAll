# Phase 4 — Server Metrics, Container Health & OpenRouter Cost in OneRing

**Date:** 2026-06-05
**Status:** Approved (design)
**Repo:** OneRingToRuleThemAll

## Goal

Let OneRing answer natural-language questions about the homelab over Telegram/Discord:

- Live system health (CPU, RAM, disk, temperature)
- Container status, including true Docker **healthy/unhealthy** state and counts
- Metric trends over time (peak/avg over a window)
- Container log search (Loki)
- OpenRouter spend: live balance and dated usage (last 30 days)

Read-only observability exposed as **native tools** alongside the existing
vehicle/game/watch tools — no MCP server/client, no new containers.

## Architecture

OneRing's agent already uses plain OpenAI-format tool schemas in `bot/functions.py`
(`TOOLS` list + `_FUNCTION_MAP` + `dispatch(name, args, user_id)` calling
`fn(user_id, **args)`). All new tools follow this exact contract and return
**concise formatted strings** (never raw JSON) so the model relays them faithfully
(addresses the prior gpt-4o-mini/DeepSeek fidelity concern).

Three new helper modules, mirroring the `utils/itad.py` / `utils/watches.py` style
(httpx, small pure functions):

| Module | Talks to | Responsibility |
|---|---|---|
| `utils/metrics.py` | Prometheus `:9090`, Loki `:3100` (HTTP) | Instant/range PromQL, LogQL, canned query map, envelope parsing |
| `utils/docker_status.py` | Docker Engine API via `/var/run/docker.sock` | Per-container state + health + restart count |
| `utils/openrouter_usage.py` | `openrouter.ai/api/v1` (HTTP) | Balance (`/credits`) + dated usage (`/activity`) |

## Tool surface (8 tools)

### Metrics & logs (`utils/metrics.py`)

1. **`get_system_health()`** — snapshot: CPU %, RAM %, disk %, CPU temp. One call,
   formatted summary. Maps to canned PromQL.
2. **`get_metric_range(metric, duration)`** — a canned metric over a window
   (e.g. `cpu_percent`, `24h`) → min / max / avg / latest.
3. **`search_logs(container, level?, duration?)`** — Loki lines for a container,
   optional level filter (e.g. `error`) and lookback (default `1h`).
4. **`query_prometheus(promql, range?)`** — raw PromQL escape hatch (instant, or
   range when `range` like `6h` is given).
5. **`query_loki(logql, duration?)`** — raw LogQL escape hatch.

**Canned metric map** (`_CANNED` in `utils/metrics.py`):

| Friendly name | PromQL |
|---|---|
| `cpu_percent` | `100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)` |
| `ram_percent` | `(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100` |
| `disk_percent` | `(1 - node_filesystem_avail_bytes{mountpoint="/",fstype!="tmpfs"} / node_filesystem_size_bytes{mountpoint="/",fstype!="tmpfs"}) * 100` |
| `cpu_temp` | `max(node_hwmon_temp_celsius)` |

`get_metric_range` accepts these friendly names (not raw PromQL) and wraps them in
`max_over_time` / `avg_over_time` / `min_over_time` as needed for the summary.

### Container status (`utils/docker_status.py`)

6. **`get_container_status(name?)`** — reads Docker Engine API
   `GET /containers/json?all=1` over the mounted socket. Returns counts
   (total / running / stopped / **unhealthy** / restarting) and a per-container list
   with state, health, and restart count. When `name` is given, filters to that
   container and enriches with CPU/mem from cAdvisor (`container_*` by `name`).

   Health is parsed from the Docker `Status` string, which carries
   `(healthy)` / `(unhealthy)` / `(health: starting)` for containers that define a
   healthcheck; containers without a healthcheck report state only (running/exited).

### OpenRouter cost (`utils/openrouter_usage.py`)

7. **`get_openrouter_balance()`** — `GET /api/v1/credits` →
   balance = `total_credits − total_usage`, plus lifetime purchased/used.
8. **`get_openrouter_usage(start_date?, end_date?)`** — sums `GET /api/v1/activity`
   spend across the requested dates. **Clamped to the last 30 completed UTC days**
   (API limit); if a wider/older range is asked, returns an honest note and reports
   what is available. Defaults (no args) to last 30 days total. Optionally breaks
   down by model/endpoint.

Both billing tools require `OPENROUTER_PROVISIONING_KEY` (an OpenRouter
**management key**, distinct from the inference `OPENROUTER_API_KEY`). If unset, the
tools return a clear "not configured — add OPENROUTER_PROVISIONING_KEY" message
rather than erroring.

## System prompt

Add a bullet to `SYSTEM_PROMPT` in `ai/graph.py` describing the new capability:
monitor server health, container status/health, metric trends, logs, and OpenRouter
spend. Steer the model to prefer the canned helpers (`get_system_health`,
`get_container_status`, `get_metric_range`, `search_logs`) and use the raw
`query_prometheus`/`query_loki` tools only for unusual questions.

## Networking & configuration

OneRing's container currently joins only the external `master_db_postgres_default`
network. Prometheus (`:9090`) and Loki (`:3100`) publish to the host, so rather than
coupling to the grafana-stack network we reach them via the host gateway.

`docker-compose.yml` additions:

```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
```

`.env` / `.env.example` additions:

```
# Monitoring (Prometheus + Loki, published on the host)
PROMETHEUS_URL=http://host.docker.internal:9090
LOKI_URL=http://host.docker.internal:3100

# OpenRouter management key (balance + usage) — distinct from OPENROUTER_API_KEY
OPENROUTER_PROVISIONING_KEY=
```

Prometheus and Loki are unauthenticated on the LAN — no credentials needed.

### Security note

Mounting `/var/run/docker.sock` grants the bot full Docker Engine API access; the
`:ro` flag is cosmetic because the socket exposes the entire API. Accepted tradeoff
for a single-owner homelab bot. Mitigation: only read-only status tools are
implemented — no container create/exec/stop tools, and the LLM is never given a tool
that mutates Docker.

## Error handling

- HTTP failures (timeout, connection refused, non-2xx) → each tool catches and
  returns a short human-readable message (e.g. "Prometheus is unreachable"), never a
  stack trace. The existing `dispatch()` wrapper already catches exceptions as a
  backstop.
- Empty query results → explicit "no data" message, not an empty string.
- Missing `OPENROUTER_PROVISIONING_KEY` → "not configured" message.
- Docker socket absent/denied → "Docker status unavailable (socket not mounted)".

## Testing

`tests/test_metrics.py`, `tests/test_docker_status.py`, `tests/test_openrouter_usage.py`
— unit tests with mocked httpx / mocked socket responses (no live network or daemon):

- Canned PromQL builders produce the expected query strings.
- Prometheus instant + range and Loki envelope parsing, including empty-result and
  error cases.
- Docker `Status` string parsing → correct health classification
  (healthy / unhealthy / starting / no-healthcheck) and counts.
- OpenRouter credits + activity parsing, 30-day clamping, and the unset-key path.
- Formatted-string output shape for each tool.

## Out of scope (YAGNI)

- No MCP server or MCP client.
- No Grafana dashboard creation or alerting changes (Grafana already alerts to
  Telegram).
- No write/mutate operations on Docker, metrics, or anything else.
- No usage history beyond OpenRouter's 30-day activity window.

## Required user actions (post-merge, to go live)

1. Create an OpenRouter **management key** and set `OPENROUTER_PROVISIONING_KEY` in
   `.env`.
2. Set `PROMETHEUS_URL` / `LOKI_URL` (defaults assume the host-gateway reach).
3. `docker compose up --build -d` (picks up the socket mount + extra_hosts).
