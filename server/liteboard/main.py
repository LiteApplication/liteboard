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
from .config import data_dir, ensure_session_secret, ensure_setup_token, get_settings
from .setup import router as setup_router
from .state import init_state

STATIC_DIR = Path(os.environ.get("LITEBOARD_STATIC_DIR", "/app/static"))


def _announce_setup(settings) -> None:
    """When unconfigured, print the setup token so the operator can unlock the
    first-login wizard (visible via ``docker service logs liteboard_server``)."""
    if settings.is_configured:
        return
    token = ensure_setup_token()
    print(
        "\n" + "=" * 68 + "\n"
        "  LiteBoard is UNCONFIGURED.\n"
        f"  Open {settings.base_url} and complete the setup wizard.\n"
        f"  Setup token:  {token}\n"
        + "=" * 68 + "\n",
        flush=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    state = init_state()
    state.start()
    try:
        yield
    finally:
        await state.stop()


def create_app() -> FastAPI:
    # Ensure the runtime data dir exists and a stable session secret is present
    # before wiring middleware (both survive across restarts via the volume).
    data_dir().mkdir(parents=True, exist_ok=True)
    session_secret = ensure_session_secret()

    settings = get_settings()
    _announce_setup(settings)

    app = FastAPI(title="LiteBoard", version=__version__, lifespan=lifespan)

    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret,
        https_only=settings.base_url.startswith("https"),
        same_site="lax",
    )

    app.include_router(setup_router)
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
