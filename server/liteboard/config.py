"""Environment-driven configuration."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LITEBOARD_", extra="ignore")

    # --- General ---------------------------------------------------------- #
    base_url: str = Field("http://localhost:8000", description="Public base URL")
    session_secret: str = Field("change-me-in-production")
    docker_host: str = Field("unix:///var/run/docker.sock")

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
    # Signing key: prefer the Docker secret file, fall back to an env value.
    signing_key_file: str = "/run/secrets/liteboard_signing_key"
    signing_key: str = ""  # base64/PEM inline (dev only)

    # --- Registry --------------------------------------------------------- #
    # Path to a Docker config.json containing registry auths (private repos).
    registry_config_file: str = "/run/secrets/liteboard_registry_creds"
    registry_check_interval: float = 300.0

    @property
    def redirect_uri(self) -> str:
        return self.base_url.rstrip("/") + "/auth/callback"

    def load_signing_key(self) -> bytes:
        """Return the raw signing key material (PEM or base64 seed bytes)."""
        path = Path(self.signing_key_file)
        if path.is_file():
            return path.read_bytes()
        if self.signing_key:
            return self.signing_key.encode()
        raise RuntimeError(
            "No signing key found. Provide the 'liteboard_signing_key' Docker "
            "secret or set LITEBOARD_SIGNING_KEY (see `make keygen`)."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
