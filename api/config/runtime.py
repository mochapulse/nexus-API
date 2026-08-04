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
"""

import os

from dotenv import load_dotenv
from api.config.paths import DOTENV_PATH

load_dotenv(dotenv_path=str(DOTENV_PATH))

APP_NAME = os.getenv("APP_NAME", "Nexus API")
PORT = int(os.getenv("PORT", 8000))
DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "t")
API_KEY = os.getenv("API_KEY", "")
