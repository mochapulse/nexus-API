"""Nexus API application entry point.

A FastAPI server that serves health, telemetry, and power-management
endpoints backed by JSONC response templates.  Run with::

    python -m api.main
"""

from fastapi import FastAPI
from fastapi.responses import FileResponse
import psutil

from api.config.paths import DOTENV_PATH, FAVICON_PATH, ensure_dotenv
from api.lib.templates import load_template
from api.hw.stats import get_system_metrics
from api.hw.power import system_poweroff

ensure_dotenv()

import api.config.runtime as runtime

# Warm up CPU timers
psutil.cpu_percent(interval=None)

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
    if runtime.DEBUG:
        print("Dummy POST /power/poweroff")
        return load_template("post-poweroff")
    else:
        
        system_poweroff()
        return load_template("post-poweroff")


@app.post("/power/sleep")
def post_sleep():
    """Return the ``post-sleep`` JSONC template."""
    return load_template("post-sleep")


@app.post("/telemetry")
async def post_telemetry():

    return await get_system_metrics(pretty=True)


if __name__ == "__main__":
    import uvicorn
    print(f"Listening WSL->Windows DEV on http://localhost:{runtime.PORT}")
    uvicorn.run("api.main:app", host="0.0.0.0", port=runtime.PORT, reload=runtime.DEBUG)
