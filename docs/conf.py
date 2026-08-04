"""Sphinx configuration for the Nexus API documentation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

project = "Nexus API"
copyright = "2026, Mocha Pulse"
author = "Mocha Pulse"
release = "0.1.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "furo"
html_title = "Nexus API"
html_static_path = ["_static"]

html_favicon = str(Path(__file__).resolve().parents[1] / "frontend" / "public" / "favicon.svg")

html_theme_options = {
    "source_repository": "https://github.com/mochapulse/nexus-API",
    "source_branch": "main",
    "source_directory": "docs/",
}

autodoc_typehints = "description"
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "fastapi": ("https://fastapi.tiangolo.com", None),
}
