"""Tests for the DEBUG-gated /api/v1/mc-server/watchdog endpoints and the
lifespan wiring that starts/stops the watchdog polling loop.

``watchdog.STATE`` is reset to a fresh ``WatchdogState()`` before every
test so arm/disarm state never leaks between tests. Production-mode
lifespan tests patch ``main.watchdog_loop`` before the lifespan runs so
this suite never starts a real polling task, probes a socket, or calls
systemctl.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import api.config.runtime as runtime
from api import main
from api.lib.templates import load_template
from api.mc import watchdog as mc_watchdog
from api.mc.watchdog import WatchdogState


@pytest.fixture(autouse=True)
def _reset_watchdog_state():
    """Isolate the module-level watchdog.STATE singleton across tests."""
    original = mc_watchdog.STATE
    mc_watchdog.STATE = WatchdogState()
    yield
    mc_watchdog.STATE = original


class TestGetWatchdogEndpoint:
    def test_requires_api_key(self, client):
        response = client.get("/api/v1/mc-server/watchdog")
        assert response.status_code == 401

    def test_debug_returns_stub_and_leaves_state_untouched(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", True)

        response = client.get("/api/v1/mc-server/watchdog", headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == load_template("get-mc-server-watchdog")
        assert mc_watchdog.STATE.armed is False

    def test_production_returns_live_snapshot(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", False)
        mc_watchdog.arm(mc_watchdog.STATE, now=0.0, active_seconds=100, threshold_seconds=30)

        response = client.get("/api/v1/mc-server/watchdog", headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["armed"] is True
        assert body["threshold_seconds"] == 30


class TestPostWatchdogEndpoint:
    def test_requires_api_key(self, client):
        response = client.post("/api/v1/mc-server/watchdog", json={"active_seconds": 100})
        assert response.status_code == 401

    def test_debug_returns_stub_and_leaves_state_untouched(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", True)

        response = client.post(
            "/api/v1/mc-server/watchdog",
            json={"active_seconds": 18000},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json() == load_template("post-mc-server-watchdog")
        assert mc_watchdog.STATE.armed is False

    def test_debug_still_validates_body(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", True)

        response = client.post(
            "/api/v1/mc-server/watchdog",
            json={"active_seconds": 0},
            headers=auth_headers,
        )

        assert response.status_code == 422

    def test_production_arms_with_default_threshold(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", False)

        response = client.post(
            "/api/v1/mc-server/watchdog",
            json={"active_seconds": 3600},
            headers=auth_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["armed"] is True
        assert body["threshold_seconds"] == mc_watchdog.DEFAULT_THRESHOLD
        assert 3595 <= body["remaining_seconds"] <= 3600
        assert mc_watchdog.STATE.armed is True

    def test_production_arms_with_explicit_threshold(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", False)

        response = client.post(
            "/api/v1/mc-server/watchdog",
            json={"active_seconds": 3600, "threshold_seconds": 600},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["threshold_seconds"] == 600

    def test_rearm_resets_counters(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", False)
        mc_watchdog.arm(mc_watchdog.STATE, now=0.0, active_seconds=100, threshold_seconds=30)
        mc_watchdog.STATE.restarts_used = 2
        mc_watchdog.STATE.empty_since = 10.0

        response = client.post(
            "/api/v1/mc-server/watchdog",
            json={"active_seconds": 200},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert mc_watchdog.STATE.restarts_used == 0
        assert mc_watchdog.STATE.empty_since is None

    @pytest.mark.parametrize(
        "payload",
        [
            {"active_seconds": 0},
            {"active_seconds": -5},
            {},
            {"active_seconds": 7 * 24 * 3600 + 1},
            {"active_seconds": 3600, "threshold_seconds": 0},
            {"active_seconds": 3600, "threshold_seconds": 24 * 3600 + 1},
        ],
    )
    def test_invalid_body_returns_422(self, client, auth_headers, monkeypatch, payload):
        monkeypatch.setattr(runtime, "DEBUG", False)

        response = client.post(
            "/api/v1/mc-server/watchdog", json=payload, headers=auth_headers
        )

        assert response.status_code == 422
        assert mc_watchdog.STATE.armed is False


class TestDeleteWatchdogEndpoint:
    def test_requires_api_key(self, client):
        response = client.delete("/api/v1/mc-server/watchdog")
        assert response.status_code == 401

    def test_debug_returns_stub_and_leaves_state_untouched(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", True)

        response = client.delete("/api/v1/mc-server/watchdog", headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == load_template("delete-mc-server-watchdog")
        assert mc_watchdog.STATE.armed is False
        assert mc_watchdog.STATE.last_disarm_reason is None

    def test_production_disarms_with_manual_reason(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", False)
        mc_watchdog.arm(mc_watchdog.STATE, now=0.0, active_seconds=100, threshold_seconds=30)

        response = client.delete("/api/v1/mc-server/watchdog", headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["armed"] is False
        assert body["last_disarm_reason"] == "manual"
        assert mc_watchdog.STATE.armed is False

    def test_idempotent_when_already_disarmed(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", False)

        response = client.delete("/api/v1/mc-server/watchdog", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["armed"] is False
        assert response.json()["last_disarm_reason"] == "manual"


class TestWatchdogLifespan:
    def test_debug_never_starts_watchdog_loop(self, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", True)
        mock_loop = AsyncMock()
        monkeypatch.setattr(main, "watchdog_loop", mock_loop)

        with TestClient(main.app):
            pass

        mock_loop.assert_not_called()

    def test_production_starts_watchdog_loop(self, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", False)
        monkeypatch.setattr(runtime, "DUCKDNS_DOMAIN", "")
        monkeypatch.setattr(runtime, "DUCKDNS_TOKEN", "")
        mock_loop = AsyncMock()
        monkeypatch.setattr(main, "watchdog_loop", mock_loop)

        with TestClient(main.app):
            pass

        mock_loop.assert_called_once_with(
            "localhost", runtime.MINECRAFT_PORT, runtime.MINECRAFT_SERVICE
        )
