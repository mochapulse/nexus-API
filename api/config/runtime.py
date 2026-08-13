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
