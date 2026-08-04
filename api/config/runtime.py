
import os

from dotenv import load_dotenv
from api.config.paths import DOTENV_PATH

load_dotenv(dotenv_path=str(DOTENV_PATH))

APP_NAME = os.getenv("APP_NAME", "Nexus API")
PORT = int(os.getenv("PORT", 8000))
DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "t")
