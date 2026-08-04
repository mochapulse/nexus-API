"""Nexus API application entry point.

A FastAPI server that serves health, telemetry, and power-management
endpoints backed by JSONC response templates.  Run with::

    python -m api.main
"""

from fastapi import FastAPI
from fastapi.responses import FileResponse

from api.config.paths import DOTENV_PATH, FAVICON_PATH, ensure_dotenv
from api.lib.templates import load_template

ensure_dotenv()

import api.config.runtime as runtime

app = FastAPI(
    title=runtime.APP_NAME,
    debug=runtime.DEBUG,
)


@app.get("/")
def read_root():
    """Root health-check — confirms the API is alive."""
    return {"msg": f"Nexus API is running! ({runtime.APP_NAME})"}


@app.get("/favicon.ico")
async def favicon():
    """Serve the Nexus favicon as an SVG."""
    return FileResponse(FAVICON_PATH, media_type="image/svg+xml")


@app.get("/health")
def get_health():
    """Return the ``get-health`` JSONC template."""
    return load_template("get-health")


@app.post("/power/poweroff")
def post_poweroff():
    """Return the ``post-poweroff`` JSONC template."""
    return load_template("post-poweroff")


@app.post("/power/sleep")
def post_sleep():
    """Return the ``post-sleep`` JSONC template."""
    return load_template("post-sleep")


@app.post("/telemetry")
def post_telemetry():
    """Return the ``post-telemetry`` JSONC template."""
    return load_template("post-telemetry")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=runtime.PORT, reload=runtime.DEBUG)
