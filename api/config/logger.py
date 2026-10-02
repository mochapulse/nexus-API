"""Cross-platform colored logger with caller context.

Provides a ``get_logger`` factory that attaches a colored, timestamped
formatter to each named logger.  Call once per module::

    from api.config.logger import get_logger
    log = get_logger(__name__)
"""

import logging
import os
import sys

_COLORS = {
    "DEBUG": "\033[90m",
    "INFO": "\033[35m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
}
_RESET = "\033[0m"
_DIM = "\033[2m"


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
            return True
        except Exception:
            return False
    return hasattr(sys.stderr, "isatty") and sys.stderr.isatty()


class ColoredFormatter(logging.Formatter):

    def __init__(self, use_color: bool = True):
        super().__init__(
            fmt="[%(asctime)s] %(levelname)s %(name)s.%(funcName)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        if self.use_color:
            color = _COLORS.get(record.levelname, "")
            record.levelname = f"{color}{record.levelname}{_RESET}"
            record.name = f"{_DIM}{record.name}{_RESET}"
        return super().format(record)


def get_logger(name: str, level: int = logging.DEBUG) -> logging.Logger:
    """Get a named logger with colored output on stderr."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(ColoredFormatter(use_color=_supports_color()))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def configure_uvicorn_logging() -> None:
    """Override uvicorn's default formatters with the colored one."""
    formatter = ColoredFormatter(use_color=_supports_color())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        for handler in uv_logger.handlers:
            handler.setFormatter(formatter)
