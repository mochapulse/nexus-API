"""Nexus API application entry point.

A FastAPI server that serves health, telemetry, and power-management
endpoints backed by JSONC response templates.  All business routes live
under the versioned ``/api/v1`` prefix; only the favicon stays at the
root.  Run with::

    python -m api.main
"""

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
import psutil

from api.config.paths import FAVICON_PATH, ensure_dotenv
from api.lib.templates import load_template
from api.hw.stats import get_system_metrics
from api.hw.power import system_poweroff, system_sleep

ensure_dotenv()

import api.config.runtime as runtime

# Warm up CPU timers
psutil.cpu_percent(interval=None)

app = FastAPI(
    title=runtime.APP_NAME,
    debug=runtime.DEBUG,
)

api_v1_router = APIRouter(prefix="/api/v1")


@api_v1_router.get("/")
def read_root():
    """Root health-check — confirms the API is alive."""
    return {"msg": f"Nexus API is running! ({runtime.APP_NAME})"}


@api_v1_router.get("/health")
def get_health():
    """Return the ``get-health`` JSONC template."""
    return load_template("get-health")


@api_v1_router.post("/power/poweroff")
def post_poweroff():
    """Power off the host system.

    On success the response is ``{"poweroff_triggered": "true"}``.
    When ``DEBUG`` is enabled, the real command is skipped and a stub
    template is returned instead, so the machine cannot be shut down
    accidentally during development.
    """
    if runtime.DEBUG:
        return load_template("post-poweroff")
    error = system_poweroff()
    if error:
        return JSONResponse(status_code=500, content={"status": "error", "detail": error})
    return {"poweroff_triggered": "true"}


@api_v1_router.post("/power/sleep")
def post_sleep():
    """Put the host system into S3 (suspend-to-RAM) sleep.

    On success the response is ``{"sleep_triggered": "true"}``.
    When ``DEBUG`` is enabled, the real command is skipped and a stub
    template is returned instead, so the machine cannot be suspended
    accidentally during development.
    """
    if runtime.DEBUG:
        return load_template("post-sleep")
    error = system_sleep()
    if error:
        return JSONResponse(status_code=500, content={"status": "error", "detail": error})
    return {"sleep_triggered": "true"}


@api_v1_router.get("/telemetry")
async def get_telemetry():
    """Return live hardware telemetry (CPU, RAM, swap, GPU).

    The payload is pre-serialized by orjson in the metrics worker and
    served as raw bytes with a standard ``application/json`` media type,
    so no re-serialization occurs on the response path.
    """
    body = await get_system_metrics(pretty=True, return_bytes=True)
    return Response(content=body, media_type="application/json")


app.include_router(api_v1_router)


@app.get("/favicon.ico")
async def favicon():
    """Serve the Nexus favicon as an SVG."""
    return FileResponse(FAVICON_PATH, media_type="image/svg+xml")


if __name__ == "__main__":
    import uvicorn
    print(f"Listening WSL->Windows DEV on http://localhost:{runtime.PORT}")
    uvicorn.run("api.main:app", host="0.0.0.0", port=runtime.PORT, reload=runtime.DEBUG)
