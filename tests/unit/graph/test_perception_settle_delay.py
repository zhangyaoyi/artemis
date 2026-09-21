import json
from types import SimpleNamespace

from artemis.graph.perception import _settle_delay_seconds


def _state(action):
    return SimpleNamespace(structured_decisions=json.dumps([{"action": action}]))


def test_default_delay(monkeypatch):
    monkeypatch.delenv("ARTEMIS_SETTLE_DELAY", raising=False)
    assert _settle_delay_seconds(_state("click")) == 1.5


def test_env_override(monkeypatch):
    monkeypatch.setenv("ARTEMIS_SETTLE_DELAY", "2.5")
    assert _settle_delay_seconds(_state("click")) == 2.5


def test_launch_app_longer(monkeypatch):
    monkeypatch.delenv("ARTEMIS_SETTLE_DELAY", raising=False)
    assert _settle_delay_seconds(_state("launch_app")) == 3.0


def test_bad_decisions_fall_back(monkeypatch):
    monkeypatch.delenv("ARTEMIS_SETTLE_DELAY", raising=False)
    assert _settle_delay_seconds(SimpleNamespace(structured_decisions="x")) == 1.5


def test_manage_app_longer(monkeypatch):
    monkeypatch.delenv("ARTEMIS_SETTLE_DELAY", raising=False)
    assert _settle_delay_seconds(_state("manage_app")) == 3.0


def test_skip_settling_matches_previous_semantics():
    from artemis.graph.perception import _should_skip_settling

    assert _should_skip_settling(SimpleNamespace(structured_decisions="")) is True
    assert _should_skip_settling(SimpleNamespace(structured_decisions="[]")) is True
    assert _should_skip_settling(_state("wait_for_delay")) is True
    assert _should_skip_settling(_state("click")) is False
    assert _should_skip_settling(SimpleNamespace(structured_decisions="[{}]")) is False
    assert _should_skip_settling(SimpleNamespace(structured_decisions="x")) is False
