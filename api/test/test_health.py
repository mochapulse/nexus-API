"""Tests for the /api/v1/health liveness probe."""


class TestHealthEndpoint:
    def test_health_returns_200_with_key(self, client, auth_headers):
        response = client.get("/api/v1/health", headers=auth_headers)
        assert response.status_code == 200

    def test_health_payload_shape(self, client, auth_headers):
        body = client.get("/api/v1/health", headers=auth_headers).json()
        assert body["status"] == "ok"
        assert isinstance(body["version"], str) and body["version"]
        assert isinstance(body["uptime_seconds"], int)
        assert isinstance(body["timestamp"], int)
        assert "last_duckdns_update_ms" in body
        assert "connectivity_delay_ms" in body

    def test_health_forbids_caching(self, client, auth_headers):
        response = client.get("/api/v1/health", headers=auth_headers)
        assert response.headers["cache-control"] == "no-store"

    def test_health_uptime_monotonic(self, client, auth_headers):
        first = client.get("/api/v1/health", headers=auth_headers).json()
        second = client.get("/api/v1/health", headers=auth_headers).json()
        assert second["uptime_seconds"] >= first["uptime_seconds"]
