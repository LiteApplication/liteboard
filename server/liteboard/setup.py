"""First-login setup wizard (public, pre-authentication).

The stack deploys with no configuration. This router lets an operator turn an
*unconfigured* server into a configured one:

  1. ``GET /api/setup/status``  — is the server configured yet?
  2. ``POST /api/setup``        — one-shot: unlock with the setup token printed
     to the server logs, provide OIDC settings, and the server generates the
     signing key, persists ``config.json``, then restarts to load it.

These routes are intentionally **not** behind ``require_user`` — there is no
auth configured yet. The setup token (a random secret only visible in the
server logs) is what gates access.
"""

from __future__ import annotations

import os
import threading

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .config import (
    get_settings,
    save_runtime_config,
    verify_setup_token,
)
from .crypto.signer import generate_signing_key

router = APIRouter(prefix="/api/setup", tags=["setup"])


class SetupPayload(BaseModel):
    token: str
    base_url: str
    oidc_issuer: str
    oidc_client_id: str
    oidc_client_secret: str
    oidc_required_group: str = ""


@router.get("/status")
async def status() -> dict:
    settings = get_settings()
    return {
        "configured": settings.is_configured,
        "auth_disabled": settings.auth_disabled,
    }


async def _probe_oidc(issuer: str) -> None:
    """Fail fast if the OIDC issuer's discovery document is unreachable.

    Committing a bad issuer would lock the operator out (the wizard disappears
    once configured), so we validate before persisting anything.
    """
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(url)
        resp.raise_for_status()
        doc = resp.json()
    except Exception as exc:  # noqa: BLE001 - surface any failure to the user
        raise HTTPException(400, f"could not reach OIDC issuer: {exc}")
    missing = [k for k in ("authorization_endpoint", "token_endpoint") if not doc.get(k)]
    if missing:
        raise HTTPException(400, f"OIDC discovery missing: {', '.join(missing)}")


def _restart_soon() -> None:
    """Exit the process so Swarm restarts it with the new config loaded."""
    threading.Timer(0.7, lambda: os._exit(0)).start()


@router.post("")
async def submit(payload: SetupPayload) -> dict:
    settings = get_settings()
    if settings.is_configured:
        raise HTTPException(409, "already configured")
    if not verify_setup_token(payload.token):
        raise HTTPException(401, "invalid setup token")

    await _probe_oidc(payload.oidc_issuer)

    # Generate the stable signing key into the data volume (idempotent).
    if not settings.has_signing_key():
        try:
            generate_signing_key(settings.signing_key_path)
        except FileExistsError:
            pass  # concurrent setup; key already there

    save_runtime_config(
        {
            "base_url": payload.base_url.rstrip("/"),
            "oidc_issuer": payload.oidc_issuer,
            "oidc_client_id": payload.oidc_client_id,
            "oidc_client_secret": payload.oidc_client_secret,
            "oidc_required_group": payload.oidc_required_group,
        }
    )

    _restart_soon()
    return {"ok": True, "restarting": True}
