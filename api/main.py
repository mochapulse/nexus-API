from fastapi import FastAPI
from fastapi.responses import FileResponse

from api.config.paths import FAVICON_PATH, ensure_dotenv

ensure_dotenv()

import api.config.runtime as runtime

app = FastAPI(
    title=runtime.APP_NAME,
    debug=runtime.DEBUG,
)


@app.get("/")
def read_root():
    return {"msg": f"Nexus API is running! ({runtime.APP_NAME})"}


@app.get("/favicon.ico")
async def favicon():
    return FileResponse(FAVICON_PATH, media_type="image/svg+xml")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=runtime.PORT, reload=runtime.DEBUG)
