
from pathlib import Path
import shutil

API_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = API_DIR.parent

DOTENV_PATH = API_DIR / ".env"
FAVICON_PATH = PROJECT_DIR / "frontend" / "public" / "favicon.svg"

def ensure_dotenv(base_dir: Path = API_DIR) -> None:
    """
    Ensures a .env file exists in the specified directory by copying
    .env.example if .env is missing.
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
