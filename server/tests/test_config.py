"""Runtime config layer: is_configured, config.json precedence, token/secret."""

import pytest

from liteboard import config as cfg
from liteboard.config import Settings
from liteboard.crypto.signer import generate_signing_key

_CLEAR = [
    "LITEBOARD_OIDC_ISSUER",
    "LITEBOARD_OIDC_CLIENT_ID",
    "LITEBOARD_OIDC_CLIENT_SECRET",
    "LITEBOARD_AUTH_DISABLED",
    "LITEBOARD_SIGNING_KEY_FILE",
    "LITEBOARD_SIGNING_KEY",
    "LITEBOARD_SESSION_SECRET",
]


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LITEBOARD_DATA_DIR", str(tmp_path))
    for k in _CLEAR:
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def _write_oidc(data_dir):
    cfg.save_runtime_config(
        {
            "oidc_issuer": "https://idp/application/o/lb/",
            "oidc_client_id": "cid",
            "oidc_client_secret": "sec",
        }
    )


def test_unconfigured_by_default(data_dir):
    assert Settings().is_configured is False


def test_configured_needs_oidc_and_key(data_dir):
    _write_oidc(data_dir)
    # OIDC present but still no signing key.
    assert Settings().is_configured is False
    generate_signing_key(Settings().signing_key_path)
    assert Settings().is_configured is True


def test_auth_disabled_short_circuits(data_dir, monkeypatch):
    monkeypatch.setenv("LITEBOARD_AUTH_DISABLED", "true")
    assert Settings().is_configured is True


def test_env_overrides_config_json(data_dir, monkeypatch):
    _write_oidc(data_dir)
    monkeypatch.setenv("LITEBOARD_OIDC_ISSUER", "https://from-env/")
    assert Settings().oidc_issuer == "https://from-env/"


def test_setup_token_roundtrip(data_dir):
    token = cfg.ensure_setup_token()
    assert token and cfg.ensure_setup_token() == token  # stable
    assert cfg.verify_setup_token(token) is True
    assert cfg.verify_setup_token("wrong") is False
    assert cfg.verify_setup_token("") is False


def test_session_secret_generated_and_persisted(data_dir):
    first = cfg.ensure_session_secret()
    assert first and len(first) >= 32
    assert cfg.ensure_session_secret() == first  # persisted, not regenerated


def test_signing_key_path_defaults_into_data_dir(data_dir):
    assert Settings().signing_key_path == data_dir / "signing_key"
