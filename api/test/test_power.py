"""Tests for the DEBUG-gated /api/v1/power endpoints.

The systemctl commands are mocked so no real poweroff/suspend can ever
happen, even when exercising the production (non-DEBUG) code path.
"""

import api.config.runtime as runtime
from api import main


class TestPoweroffEndpoint:
    def test_debug_returns_stub_without_executing(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", True)
        executed = []
        monkeypatch.setattr(main, "system_poweroff", lambda: executed.append("ran"))

        response = client.post("/api/v1/power/poweroff", headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == {"poweroff_triggered": "true"}
        assert executed == [], "DEBUG stub must never run systemctl"

    def test_production_executes_and_returns_triggered(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", False)
        monkeypatch.setattr(main, "system_poweroff", lambda: None)

        response = client.post("/api/v1/power/poweroff", headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == {"poweroff_triggered": "true"}

    def test_production_failure_returns_500(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", False)
        monkeypatch.setattr(main, "system_poweroff", lambda: "systemctl exited 1")

        response = client.post("/api/v1/power/poweroff", headers=auth_headers)

        assert response.status_code == 500
        assert response.json() == {"status": "error", "detail": "systemctl exited 1"}


class TestSleepEndpoint:
    def test_debug_returns_stub_without_executing(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", True)
        executed = []
        monkeypatch.setattr(main, "system_sleep", lambda: executed.append("ran"))

        response = client.post("/api/v1/power/sleep", headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == {"sleep_triggered": "true"}
        assert executed == [], "DEBUG stub must never run systemctl"

    def test_production_executes_and_returns_triggered(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", False)
        monkeypatch.setattr(main, "system_sleep", lambda: None)

        response = client.post("/api/v1/power/sleep", headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == {"sleep_triggered": "true"}

    def test_production_failure_returns_500(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", False)
        monkeypatch.setattr(main, "system_sleep", lambda: "systemctl exited 1")

        response = client.post("/api/v1/power/sleep", headers=auth_headers)

        assert response.status_code == 500
        assert response.json() == {"status": "error", "detail": "systemctl exited 1"}
