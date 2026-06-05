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
