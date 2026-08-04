"""Tests for the /api/v1/telemetry endpoint (real hardware metrics)."""


class TestTelemetryEndpoint:
    def test_telemetry_returns_200_with_key(self, client, auth_headers):
        response = client.get("/api/v1/telemetry", headers=auth_headers)
        assert response.status_code == 200

    def test_telemetry_payload_shape(self, client, auth_headers):
        body = client.get("/api/v1/telemetry", headers=auth_headers).json()
        assert isinstance(body["uptime_seconds"], int)
        assert isinstance(body["cpu"]["overall_usage_percent"], (int, float))
        assert isinstance(body["cpu"]["per_core_percent"], list)
        for core in body["cpu"]["per_core_percent"]:
            assert isinstance(core, (int, float))
        for key in ("total_bytes", "used_bytes", "free_bytes", "usage_percent"):
            assert key in body["ram"]
        for key in ("total_bytes", "used_bytes", "usage_percent"):
            assert key in body["swap"]
        assert isinstance(body["gpu"], list)

    def test_gpu_entries_have_full_schema(self, client, auth_headers):
        gpus = client.get("/api/v1/telemetry", headers=auth_headers).json()["gpu"]
        for gpu in gpus:
            for key in (
                "index",
                "vendor",
                "name",
                "gpu_usage_percent",
                "vram_used_bytes",
                "vram_total_bytes",
                "temperature_c",
            ):
                assert key in gpu
