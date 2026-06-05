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
