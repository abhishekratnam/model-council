import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from app.core.memory import memory_store
from app.core.config import logger, settings,  STATIC_DIR
from app.core.exceptions import CouncilError, ProviderError
from app.services.security import is_safe_browser_origin, scrub_secrets, is_loopback_host
from app.api.routes import router as api_router
from app.api.websocket import router as ws_router

app = FastAPI(title="Model Council", version="2.0")

# ── Middleware ───────────────────────────────────────────────────────────────

@app.middleware("http")
async def security_headers(request: Request, call_next):
    origin = request.headers.get("Origin")
    
    # Allow FastAPI docs and OpenAPI schema to load external CDN scripts
    if request.url.path in {"/docs", "/redoc", "/openapi.json"}:
        return await call_next(request)

    if request.url.path.startswith("/api/") and not is_safe_browser_origin(origin):
        return JSONResponse(
            status_code=403,
            content={"error": "This server does not accept requests from this browser origin."},
        )

    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; connect-src 'self' http://localhost:* http://127.0.0.1:* ws://localhost:* ws://127.0.0.1:* https:; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    )
    return response

# ── Exception Handlers ───────────────────────────────────────────────────────

@app.exception_handler(CouncilError)
async def council_error_handler(_: Request, exc: CouncilError):
    return JSONResponse(status_code=400, content={"error": scrub_secrets(str(exc))})

@app.exception_handler(ProviderError)
async def provider_error_handler(_: Request, exc: ProviderError):
    return JSONResponse(status_code=502, content={"error": scrub_secrets(str(exc))})

@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, __: Exception):
    return JSONResponse(status_code=500, content={"error": "Unexpected server error."})

# ── Routers ─────────────────────────────────────────────────────────────────

app.include_router(api_router, prefix="/api")
app.include_router(ws_router, prefix="/api")

# ── Static Files ─────────────────────────────────────────────────────────────

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

# Use the centralized STATIC_DIR
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

@app.get("/")
@app.get("/index.html")
async def index():
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

@app.get("/styles.css")
async def styles():
    return FileResponse(STATIC_DIR / "styles.css", media_type="text/css")

@app.get("/app.js")
async def app_js():
    return FileResponse(STATIC_DIR / "app.js", media_type="text/javascript")

# ── Entrypoint ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    host = settings.HOST
    port = settings.PORT

    if not is_loopback_host(host) and not settings.MODEL_COUNCIL_ALLOW_NETWORK:
        raise SystemExit(
            "Refusing a non-loopback bind. Set MODEL_COUNCIL_ALLOW_NETWORK=1 only if intentional."
        )

    logger.info("Starting Model Council on %s:%s", host, port)
    logger.info("Memory store: %s", "available" if memory_store.available else "disabled")
    
    # Run uvicorn pointing to app.main:app
    uvicorn.run("app.main:app", host=host, port=port, reload=True)