"""Filesystem paths and bootstrapping for the Nexus API.

Constants
---------
API_DIR : pathlib.Path
    Absolute path to the ``api/`` package directory.
PROJECT_DIR : pathlib.Path
    Absolute path to the repository root (one level above ``api/``).
DOTENV_PATH : pathlib.Path
    Path to the ``.env`` file.  Respects ``NEXUS_DOTENV_PATH`` env var
    override (used by the CLI workstation deploy alias).
FAVICON_PATH : pathlib.Path
    Path to the favicon SVG served by the FastAPI app.
TEMPLATES_DIR : pathlib.Path
    Path to the ``templates/`` directory containing JSONC response templates.
DB_PATH : pathlib.Path
    Path to the SQLite3 database file used by the Nexus API.

Functions
---------
ensure_dotenv(base_dir=API_DIR)
    Copy ``.env.example`` to ``.env`` when no ``.env`` is present.
"""

from pathlib import Path
import os
import shutil

API_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = API_DIR.parent

DOTENV_PATH = Path(os.environ.get("NEXUS_DOTENV_PATH", str(API_DIR / ".env")))
FAVICON_PATH = PROJECT_DIR / "frontend" / "public" / "favicon.svg"
TEMPLATES_DIR = PROJECT_DIR / "templates"
DB_PATH = API_DIR / "db"/ "nexus_api.db"

def ensure_dotenv(base_dir: Path = API_DIR) -> None:
    """Copy ``.env.example`` to ``.env`` when no ``.env`` is present.

    Parameters
    ----------
    base_dir : pathlib.Path
        Directory containing the ``.env`` and ``.env.example`` files.
    """
    dotenv_path = base_dir / ".env"
    example_dotenv_path = base_dir / ".env.example"

    if dotenv_path.exists():
        return

    if example_dotenv_path.exists():
        shutil.copy(example_dotenv_path, dotenv_path)
        print(f"Created '{dotenv_path.name}' from '{example_dotenv_path.name}'.")
    else:
        print(f"Warning: Neither '{dotenv_path.name}' nor '{example_dotenv_path.name}' was found in {base_dir}.")
