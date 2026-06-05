import pytest

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


@pytest.mark.parametrize("text,expected", [
    ("30s", 30), ("5m", 300), ("2h", 7200), ("1d", 86400), ("45", 45),
])
def test_duration_seconds(text, expected):
    assert metrics._duration_seconds(text) == expected
