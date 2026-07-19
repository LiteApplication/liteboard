"""Authentik OIDC integration (Authorization Code flow) + session guard."""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from ..config import Settings, get_settings

_oauth: OAuth | None = None


def _server_metadata_url(issuer: str) -> str:
    return issuer.rstrip("/") + "/.well-known/openid-configuration"


def get_oauth() -> OAuth:
    global _oauth
    if _oauth is None:
        settings = get_settings()
        oauth = OAuth()
        oauth.register(
            name="authentik",
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            server_metadata_url=_server_metadata_url(settings.oidc_issuer),
            client_kwargs={"scope": settings.oidc_scopes},
        )
        _oauth = oauth
    return _oauth


router = APIRouter()


@router.get("/auth/login")
async def login(request: Request):
    settings = get_settings()
    if settings.auth_disabled:
        return RedirectResponse(url="/")
    oauth = get_oauth()
    return await oauth.authentik.authorize_redirect(request, settings.redirect_uri)


@router.get("/auth/callback")
async def callback(request: Request):
    settings = get_settings()
    oauth = get_oauth()
    try:
        token = await oauth.authentik.authorize_access_token(request)
    except OAuthError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    userinfo = token.get("userinfo") or {}
    groups = userinfo.get("groups") or []
    if settings.oidc_required_group and settings.oidc_required_group not in groups:
        return JSONResponse(
            {"error": "not a member of the required group"}, status_code=403
        )

    request.session["user"] = {
        "sub": userinfo.get("sub"),
        "name": userinfo.get("name") or userinfo.get("preferred_username"),
        "email": userinfo.get("email"),
        "groups": groups,
    }
    return RedirectResponse(url="/")


@router.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/api/me")
async def me(request: Request):
    settings = get_settings()
    if settings.auth_disabled:
        return {"name": "Local Dev", "email": "dev@localhost", "groups": [], "auth": False}
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    return {**user, "auth": True}


def require_user(request: Request, settings: Settings = Depends(get_settings)) -> dict:
    """Dependency guarding all /api routes."""
    if settings.auth_disabled:
        return {"name": "Local Dev", "sub": "local", "groups": []}
    user = request.session.get("user")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated"
        )
    return user
