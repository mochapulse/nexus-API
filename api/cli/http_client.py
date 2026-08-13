"""HTTP client helpers for Nexus API and ESP32 requests.

Provides thin wrappers around :mod:`httpx` that handle base URLs,
authentication headers, and TLS verification in one place.

Functions
---------
nexus_get(path)
    GET against the Nexus API server.
nexus_post(path)
    POST against the Nexus API server.
esp_get(path)
    GET against the ESP32 device (HTTPS, verify=False).
esp_post(path)
    POST against the ESP32 device (HTTPS, verify=False).
"""

import httpx

import api.config.runtime as runtime

_NEXUS_BASE = f"http://{runtime.NEXUS_IP}:{runtime.NEXUS_PORT}/api/v1"
_ESP_BASE = f"https://{runtime.ESP_IP}:{runtime.ESP_PORT}"

_NEXUS_TIMEOUT = httpx.Timeout(5.0)
_ESP_TIMEOUT = httpx.Timeout(5.0)


def nexus_get(path: str) -> httpx.Response:
    """GET ``/api/v1/{path}`` on the Nexus API server.

    Parameters
    ----------
    path : str
        Endpoint path without the ``/api/v1`` prefix (e.g. ``"health"``).

    Returns:
        :class:`httpx.Response` — caller should handle status codes.
    """
    return httpx.get(
        f"{_NEXUS_BASE}/{path}",
        headers={"X-API-Key": runtime.API_KEY},
        timeout=_NEXUS_TIMEOUT,
    )


def nexus_post(path: str) -> httpx.Response:
    """POST ``/api/v1/{path}`` on the Nexus API server.

    Parameters
    ----------
    path : str
        Endpoint path without the ``/api/v1`` prefix
        (e.g. ``"power/poweroff"``).

    Returns:
        :class:`httpx.Response` — caller should handle status codes.
    """
    return httpx.post(
        f"{_NEXUS_BASE}/{path}",
        headers={"X-API-Key": runtime.API_KEY},
        timeout=_NEXUS_TIMEOUT,
    )


def esp_get(path: str) -> httpx.Response:
    """GET ``{path}`` on the ESP32 device (HTTPS, verify=False).

    Parameters
    ----------
    path : str
        Full path on the ESP (e.g. ``"api/status"``).

    Returns:
        :class:`httpx.Response` — caller should handle status codes.
    """
    return httpx.get(
        f"{_ESP_BASE}/{path}",
        headers={"X-API-Key": runtime.ESP_API_KEY},
        verify=False,
        timeout=_ESP_TIMEOUT,
    )


def esp_post(path: str) -> httpx.Response:
    """POST ``{path}`` on the ESP32 device (HTTPS, verify=False).

    Parameters
    ----------
    path : str
        Full path on the ESP (e.g. ``"api/wol"``).

    Returns:
        :class:`httpx.Response` — caller should handle status codes.
    """
    return httpx.post(
        f"{_ESP_BASE}/{path}",
        headers={"X-API-Key": runtime.ESP_API_KEY},
        verify=False,
        timeout=_ESP_TIMEOUT,
    )
