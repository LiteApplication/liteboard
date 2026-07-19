"""LiteBoard FastAPI application."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import __version__
from .api.routes import router as api_router
from .auth.oidc import router as auth_router
from .config import get_settings
from .state import init_state

STATIC_DIR = Path(os.environ.get("LITEBOARD_STATIC_DIR", "/app/static"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    state = init_state()
    state.start()
    try:
        yield
    finally:
        await state.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="LiteBoard", version=__version__, lifespan=lifespan)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        https_only=settings.base_url.startswith("https"),
        same_site="lax",
    )

    app.include_router(auth_router)
    app.include_router(api_router)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "version": __version__}

    # Serve the built Vue SPA with history-mode fallback.
    if STATIC_DIR.is_dir():
        assets = STATIC_DIR / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        async def spa(full_path: str):
            candidate = STATIC_DIR / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            index = STATIC_DIR / "index.html"
            if index.is_file():
                return FileResponse(index)
            return JSONResponse({"error": "SPA not built"}, status_code=404)

    return app


app = create_app()
