"""src/utils/yahoo_gate.py: one Yahoo pace and 429 cooldown per server."""

import time

import pytest
from yfinance.exceptions import YFRateLimitError

from src.utils import yahoo_gate


@pytest.fixture(autouse=True)
def gate_file(tmp_path, monkeypatch):
    monkeypatch.setenv("YAHOO_GATE_FILE", str(tmp_path / "gate"))
    monkeypatch.setattr(yahoo_gate, "RATE", 2)
    monkeypatch.setattr(yahoo_gate, "BURST", 3)
    monkeypatch.setattr(yahoo_gate, "COOLDOWN", 30)
    monkeypatch.setattr(yahoo_gate, "_patient", False)


def test_web_requests_are_never_paced():
    assert [yahoo_gate.reserve() for _ in range(10)] == [0.0] * 10


def test_a_burst_goes_straight_through_then_requests_are_paced(monkeypatch):
    monkeypatch.setattr(yahoo_gate, "_patient", True)
    assert [yahoo_gate.reserve() for _ in range(3)] == pytest.approx([0, 0, 0], abs=0.05)
    assert yahoo_gate.reserve() == pytest.approx(0.5, abs=0.05)
    assert yahoo_gate.reserve() == pytest.approx(1.0, abs=0.05)


def test_cooldown_fails_fast_for_web_requests():
    yahoo_gate.record_limit()
    with pytest.raises(YFRateLimitError):
        yahoo_gate.reserve()


def test_patient_worker_waits_out_the_cooldown(monkeypatch):
    monkeypatch.setattr(yahoo_gate, "_patient", True)
    yahoo_gate.record_limit()
    assert yahoo_gate.reserve() == pytest.approx(30, abs=0.5)


def test_patient_worker_gives_up_on_a_long_cooldown(monkeypatch):
    monkeypatch.setattr(yahoo_gate, "_patient", True)
    monkeypatch.setattr(yahoo_gate, "COOLDOWN", yahoo_gate.MAX_WAIT + 60)
    yahoo_gate.record_limit()
    with pytest.raises(YFRateLimitError):
        yahoo_gate.reserve()


def test_state_is_shared_through_the_file(tmp_path):
    yahoo_gate.record_limit()
    nxt, cool = map(float, (tmp_path / "gate").read_text(encoding="utf-8").split())
    assert cool > time.time() + 25


def test_yahoo_info_survives_a_restart(tmp_path, monkeypatch):
    from src.services import compare

    monkeypatch.setenv("YAHOO_INFO_CACHE_DIR", str(tmp_path / "info"))
    compare._save_info("TCS.NS", time.time(), {"trailingPE": 25.0})
    compare._info_cache.pop("TCS.NS", None)  # a fresh process
    assert compare._yahoo_info("TCS.NS") == {"trailingPE": 25.0}
