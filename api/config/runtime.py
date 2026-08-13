"""Runtime configuration loaded from environment variables (``python-dotenv``).

Attributes
----------
APP_NAME : str
    Application name, default ``"Nexus API"``.
PORT : int
    Server listen port, default ``8000``.
DEBUG : bool
    Toggle debug mode (hot-reload, verbose logs), default ``True``.
API_KEY : str
    Shared secret required in the ``X-API-Key`` header on all ``/api/v1``
    routes, default ``""`` (unset).
DUCKDNS_DOMAIN : str
    DuckDNS subdomain name for dynamic DNS updates (e.g. ``"nexus-coffee"``),
    default ``""`` (service disabled).
DUCKDNS_TOKEN : str
    DuckDNS API token for the account that owns ``DUCKDNS_DOMAIN``,
    default ``""`` (service disabled).
NEXUS_IP : str
    Nexus API server IP for CLI requests, default ``"localhost"``.
NEXUS_PORT : int
    Nexus API server port for CLI requests, default ``8000``.
ESP_IP : str
    ESP32 device IP for WOL and status, default ``""``.
ESP_PORT : str
    ESP32 device HTTPS port, default ``""``.
ESP_API_KEY : str
    ESP32 API key for ``X-API-Key`` header, default ``""``.
"""

import os

from dotenv import load_dotenv
from api.config.paths import DOTENV_PATH

load_dotenv(dotenv_path=str(DOTENV_PATH))

APP_NAME = os.getenv("APP_NAME", "Nexus API")
PORT = int(os.getenv("PORT", 8000))
DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "t")
API_KEY = os.getenv("API_KEY", "")
DUCKDNS_DOMAIN = os.getenv("DUCKDNS_DOMAIN", "")
DUCKDNS_TOKEN = os.getenv("DUCKDNS_TOKEN", "")
NEXUS_IP = os.getenv("NEXUS_IP", "localhost")
NEXUS_PORT = int(os.getenv("NEXUS_PORT", "8000"))
ESP_IP = os.getenv("ESP_IP", "")
ESP_PORT = os.getenv("ESP_PORT", "")
ESP_API_KEY = os.getenv("ESP_API_KEY", "")
