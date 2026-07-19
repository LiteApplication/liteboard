"""Environment-driven configuration.

Values resolve in priority order: environment (``LITEBOARD_*``) > the runtime
``config.json`` written by the first-login setup wizard > built-in defaults.
This lets the stack deploy with **zero** pre-configuration — the server boots
unconfigured, the wizard fills ``config.json`` (in the ``/data`` volume), and a
restart picks it up. Advanced users can still override anything via env.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import tempfile
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

# Legacy Docker-secret mount, still honoured if present (bring-your-own-key).
_LEGACY_SECRET_PATH = "/run/secrets/liteboard_signing_key"


def data_dir() -> Path:
    """Directory holding runtime state (config, generated key, setup token)."""
    return Path(os.environ.get("LITEBOARD_DATA_DIR", "/data"))


def _config_path() -> Path:
    return data_dir() / "config.json"


def _setup_token_path() -> Path:
    return data_dir() / "setup_token"


class _JsonFileSettingsSource(PydanticBaseSettingsSource):
    """Feed ``<data_dir>/config.json`` into Settings (below env in priority)."""

    def __init__(self, settings_cls) -> None:
        super().__init__(settings_cls)
        self._data: dict = {}
        path = _config_path()
        try:
            if path.is_file():
                self._data = json.loads(path.read_text()) or {}
        except (OSError, json.JSONDecodeError):
            self._data = {}

    def get_field_value(self, field, field_name):  # pragma: no cover - unused
        return self._data.get(field_name), field_name, False

    def __call__(self) -> dict:
        return {k: v for k, v in self._data.items() if v is not None}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LITEBOARD_", extra="ignore")

    # --- General ---------------------------------------------------------- #
    base_url: str = Field("http://localhost:8000", description="Public base URL")
    session_secret: str = Field("change-me-in-production")
    docker_host: str = Field("unix:///var/run/docker.sock")
    data_dir: str = Field("/data", description="Runtime state directory")

    # --- OIDC (Authentik) ------------------------------------------------- #
    oidc_issuer: str = ""  # e.g. https://authentik.example.com/application/o/liteboard/
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid profile email"
    # Optional: restrict access to members of this Authentik group.
    oidc_required_group: str = ""
    # Set true only for local dev without an IdP.
    auth_disabled: bool = False

    # --- Daemon fan-out --------------------------------------------------- #
    daemon_port: int = 9187
    daemon_scheme: str = "http"
    daemon_timeout: float = 5.0
    poll_interval: float = 5.0
    # Signing key: empty => auto-resolve (legacy Docker secret, else data dir).
    signing_key_file: str = ""
    signing_key: str = ""  # base64/PEM inline (dev only)

    # --- Registry --------------------------------------------------------- #
    # Path to a Docker config.json containing registry auths (private repos).
    registry_config_file: str = "/run/secrets/liteboard_registry_creds"
    registry_check_interval: float = 300.0

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _JsonFileSettingsSource(settings_cls),
            file_secret_settings,
        )

    @property
    def redirect_uri(self) -> str:
        return self.base_url.rstrip("/") + "/auth/callback"

    @property
    def signing_key_path(self) -> Path:
        """Where the private signing key lives (auto-resolved if not set)."""
        if self.signing_key_file:
            return Path(self.signing_key_file)
        if Path(_LEGACY_SECRET_PATH).is_file():
            return Path(_LEGACY_SECRET_PATH)
        return Path(self.data_dir) / "signing_key"

    def has_signing_key(self) -> bool:
        return bool(self.signing_key) or self.signing_key_path.is_file()

    @property
    def is_configured(self) -> bool:
        """True once the server can actually run (or auth is disabled for dev)."""
        if self.auth_disabled:
            return True
        return bool(
            self.oidc_issuer
            and self.oidc_client_id
            and self.oidc_client_secret
            and self.has_signing_key()
        )

    def load_signing_key(self) -> bytes:
        """Return the raw signing key material (PEM or base64 seed bytes)."""
        path = self.signing_key_path
        if path.is_file():
            return path.read_bytes()
        if self.signing_key:
            return self.signing_key.encode()
        raise RuntimeError(
            "No signing key found. Complete the setup wizard, or provide the "
            "'liteboard_signing_key' Docker secret / LITEBOARD_SIGNING_KEY."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


# --------------------------------------------------------------------------- #
# Runtime state helpers (config.json, session secret, setup token)
# --------------------------------------------------------------------------- #
def _atomic_write(path: Path, text: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save_runtime_config(updates: dict) -> None:
    """Merge ``updates`` into ``<data_dir>/config.json`` (persisted, 0600)."""
    path = _config_path()
    current: dict = {}
    try:
        if path.is_file():
            current = json.loads(path.read_text()) or {}
    except (OSError, json.JSONDecodeError):
        current = {}
    current.update(updates)
    _atomic_write(path, json.dumps(current, indent=2, sort_keys=True))


def ensure_session_secret() -> str:
    """Resolve the session secret, generating + persisting one on first boot."""
    env = os.environ.get("LITEBOARD_SESSION_SECRET")
    if env:
        return env
    path = _config_path()
    try:
        if path.is_file():
            existing = (json.loads(path.read_text()) or {}).get("session_secret")
            if existing:
                return existing
    except (OSError, json.JSONDecodeError):
        pass
    generated = secrets.token_hex(32)
    save_runtime_config({"session_secret": generated})
    return generated


def read_setup_token() -> str | None:
    path = _setup_token_path()
    try:
        return path.read_text().strip() if path.is_file() else None
    except OSError:
        return None


def ensure_setup_token() -> str:
    """Return the persisted setup token, generating one if absent."""
    existing = read_setup_token()
    if existing:
        return existing
    token = secrets.token_urlsafe(24)
    _atomic_write(_setup_token_path(), token)
    return token


def verify_setup_token(provided: str) -> bool:
    stored = read_setup_token()
    if not stored or not provided:
        return False
    return hmac.compare_digest(stored, provided.strip())
