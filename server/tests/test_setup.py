"""First-login setup router: token gate, key generation, config persistence."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from liteboard import config as cfg
from liteboard import setup as setupmod

_CLEAR = [
    "LITEBOARD_OIDC_ISSUER",
    "LITEBOARD_OIDC_CLIENT_ID",
    "LITEBOARD_OIDC_CLIENT_SECRET",
    "LITEBOARD_AUTH_DISABLED",
    "LITEBOARD_SIGNING_KEY_FILE",
    "LITEBOARD_SIGNING_KEY",
]

_PAYLOAD = {
    "base_url": "https://lb.example.com",
    "oidc_issuer": "https://idp/application/o/lb/",
    "oidc_client_id": "cid",
    "oidc_client_secret": "sec",
    "oidc_required_group": "",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LITEBOARD_DATA_DIR", str(tmp_path))
    for k in _CLEAR:
        monkeypatch.delenv(k, raising=False)
    cfg.get_settings.cache_clear()
    # Don't actually restart the process or hit a real IdP during tests.
    monkeypatch.setattr(setupmod, "_restart_soon", lambda: None)

    async def _ok(_issuer):
        return None

    monkeypatch.setattr(setupmod, "_probe_oidc", _ok)

    app = FastAPI()
    app.include_router(setupmod.router)
    yield TestClient(app), tmp_path
    cfg.get_settings.cache_clear()


def test_status_unconfigured(client):
    tc, _ = client
    body = tc.get("/api/setup/status").json()
    assert body["configured"] is False


def test_rejects_bad_token(client):
    tc, _ = client
    cfg.ensure_setup_token()
    resp = tc.post("/api/setup", json={**_PAYLOAD, "token": "nope"})
    assert resp.status_code == 401


def test_completes_setup_with_valid_token(client):
    tc, data_dir = client
    token = cfg.ensure_setup_token()
    resp = tc.post("/api/setup", json={**_PAYLOAD, "token": token})
    assert resp.status_code == 200 and resp.json()["ok"] is True

    assert (data_dir / "signing_key").is_file()
    # A fresh settings load now sees a fully configured instance.
    cfg.get_settings.cache_clear()
    settings = cfg.get_settings()
    assert settings.is_configured is True
    assert settings.oidc_client_id == "cid"
    assert settings.base_url == "https://lb.example.com"
