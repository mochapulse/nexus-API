"""Tests for the X-API-Key authentication gate on /api/v1 routes."""

import pytest

import api.config.runtime as runtime
from api.main import app


class TestApiKeyAuth:
    """The key matrix: valid, invalid, missing, and unconfigured server."""

    def test_valid_key_allows_health(self, client, auth_headers):
        response = client.get("/api/v1/health", headers=auth_headers)
        assert response.status_code == 200

    def test_missing_key_rejected(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 401

    def test_wrong_key_rejected(self, client):
        response = client.get("/api/v1/health", headers={"X-API-Key": "wrong"})
        assert response.status_code == 401

    def test_key_required_on_every_route(self, client, auth_headers):
        for path in ("/api/v1/telemetry", "/api/v1/power/poweroff", "/api/v1/power/sleep"):
            denied = client.get(path) if "telemetry" in path else client.post(path)
            assert denied.status_code == 401, f"{path} must reject missing key"
            allowed = client.get(path, headers=auth_headers) if "telemetry" in path else client.post(path, headers=auth_headers)
            assert allowed.status_code == 200, f"{path} must accept the key"

    def test_fail_closed_when_key_unset_in_production(self, client, monkeypatch):
        monkeypatch.setattr(runtime, "API_KEY", "")
        monkeypatch.setattr(runtime, "DEBUG", False)
        response = client.get("/api/v1/health")
        assert response.status_code == 503

    def test_fail_open_when_key_unset_in_debug(self, client, monkeypatch):
        monkeypatch.setattr(runtime, "API_KEY", "")
        monkeypatch.setattr(runtime, "DEBUG", True)
        response = client.get("/api/v1/health")
        assert response.status_code == 200


class TestPublicRoutes:
    """Docs and app-level helpers must stay reachable without a key."""

    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/favicon.ico"])
    def test_public_endpoints_open(self, client, path):
        response = client.get(path)
        assert response.status_code == 200

    def test_root_redirects_to_docs_without_key(self, client):
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/docs"

    def test_api_root_requires_key(self, client):
        assert client.get("/api/v1/", follow_redirects=False).status_code == 401

    def test_api_root_redirects_with_key(self, client, auth_headers):
        response = client.get("/api/v1/", headers=auth_headers, follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/docs"
