"""Tests for Clean Architecture ports and adapters."""

from __future__ import annotations

from typing import Any

from geode.state import DataPort, LLMPort


class MockLLM:
    """Mock LLM adapter implementing LLMPort protocol."""

    def __init__(self, response: str = '{"key": "value"}'):
        self._response = response
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, *, temperature: float = 0.3) -> str:
        self.calls.append((system, user))
        return self._response

    def complete_json(self, system: str, user: str, *, temperature: float = 0.3) -> dict[str, Any]:
        import json

        self.calls.append((system, user))
        return json.loads(self._response)


class MockDataSource:
    """Mock data adapter implementing DataPort protocol."""

    def load_ip_info(self, ip_name: str) -> dict[str, Any]:
        return {"ip_name": ip_name, "media_type": "anime"}

    def load_monolake(self, ip_name: str) -> dict[str, Any]:
        return {"dau_current": 0, "revenue_ltm": 0}

    def load_signals(self, ip_name: str) -> dict[str, Any]:
        return {"youtube_views": 1000000}

    def load_psm_covariates(self, ip_name: str) -> dict[str, Any]:
        return {"genre": "action"}


class TestLLMPort:
    def test_mock_implements_protocol(self):
        """MockLLM satisfies LLMPort protocol (structural typing)."""
        mock: LLMPort = MockLLM()
        result = mock.complete("system", "user")
        assert isinstance(result, str)

    def test_mock_json(self):
        mock: LLMPort = MockLLM('{"score": 4.2}')
        data = mock.complete_json("system", "user")
        assert data["score"] == 4.2

    def test_call_tracking(self):
        mock = MockLLM()
        mock.complete("sys1", "usr1")
        mock.complete("sys2", "usr2")
        assert len(mock.calls) == 2


class TestDataPort:
    def test_mock_implements_protocol(self):
        """MockDataSource satisfies DataPort protocol (structural typing)."""
        source: DataPort = MockDataSource()
        ip = source.load_ip_info("Cowboy Bebop")
        assert ip["ip_name"] == "Cowboy Bebop"

    def test_load_all_data(self):
        source: DataPort = MockDataSource()
        ip = source.load_ip_info("test")
        ml = source.load_monolake("test")
        sig = source.load_signals("test")
        psm = source.load_psm_covariates("test")
        assert all(isinstance(d, dict) for d in [ip, ml, sig, psm])
