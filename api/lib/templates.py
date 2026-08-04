"""JSONC template loader for API response stubs.

Template files live in ``<project>/templates/`` and follow the naming
convention ``{method}-{name}.jsonc`` (e.g. ``get-health.jsonc``).
Comments (``// line`` and ``/* block */``) are stripped before parsing.

Functions
---------
load_template(name)
    Read and parse a JSONC template file, returning its contents as a dict.
"""

import orjson
import re

from api.config.paths import TEMPLATES_DIR


_STRIP_COMMENTS = re.compile(
    r"//.*?$|/\*.*?\*/",
    re.MULTILINE | re.DOTALL,
)


def load_template(name: str) -> dict:
    """Load a JSONC template from the templates directory.

    Parameters
    ----------
    name : str
        Template basename without extension, e.g. ``"get-health"`` for
        ``get-health.jsonc``.

    Returns
    -------
    dict
        Parsed contents of the template file.
    """
    filepath = TEMPLATES_DIR / f"{name}.jsonc"
    raw = filepath.read_text(encoding="utf-8")
    clean = _STRIP_COMMENTS.sub("", raw)
    return orjson.loads(clean)
