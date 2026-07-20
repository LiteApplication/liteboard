"""Resolve the current digest of an image tag from a Docker registry (v2 API).

Handles the anonymous bearer-token flow used by Docker Hub / public registries
and credentialed auth for private registries (creds read from a Docker
``config.json``). Used to detect when a running service's image tag (e.g.
``:latest``) has moved on the registry.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path

import httpx

_DOCKER_HUB_HOST = "registry-1.docker.io"
_DEFAULT_INDEX = "docker.io"

# Accept both classic Docker manifests and OCI images + their multi-arch indexes.
_ACCEPT = ", ".join(
    [
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
    ]
)


@dataclass
class ImageRef:
    registry: str  # network host to query (e.g. registry-1.docker.io)
    repository: str  # e.g. library/nginx
    tag: str
    digest: str | None  # @sha256:... if the ref was pinned
    original: str

    @property
    def auth_host(self) -> str:
        return self.registry


def parse_image_ref(ref: str) -> ImageRef:
    """Parse ``[registry/]repo[:tag][@sha256:...]`` into its parts."""
    original = ref
    digest = None
    if "@" in ref:
        ref, digest = ref.split("@", 1)

    # Split off a registry host: the first path component containing a '.' or ':'
    # (or being 'localhost') is a registry, else it's Docker Hub.
    registry = _DEFAULT_INDEX
    remainder = ref
    if "/" in ref:
        head, rest = ref.split("/", 1)
        if "." in head or ":" in head or head == "localhost":
            registry = head
            remainder = rest

    tag = "latest"
    if ":" in remainder:
        remainder, tag = remainder.rsplit(":", 1)
    repository = remainder

    # Docker Hub official images live under library/.
    if registry == _DEFAULT_INDEX and "/" not in repository:
        repository = f"library/{repository}"

    net_host = _DOCKER_HUB_HOST if registry == _DEFAULT_INDEX else registry
    return ImageRef(net_host, repository, tag, digest, original)


class RegistryAuth:
    """Resolves basic-auth credentials for a registry from a config.json."""

    def __init__(self, config_path: str | None = None) -> None:
        self._auths: dict[str, str] = {}
        self._sources: dict[str, str] = {}
        # 1. Load from the read-only Docker secret path (if specified)
        if config_path and Path(config_path).is_file():
            self._load(Path(config_path), source="secret")
        # 2. Load from the mutable config path in the data directory
        from ..config import data_dir
        mutable_path = data_dir() / "registry_config.json"
        if mutable_path.is_file():
            self._load(mutable_path, source="mutable")

    def _load(self, path: Path, source: str) -> None:
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for host, entry in (data.get("auths") or {}).items():
            token = entry.get("auth")
            if not token and entry.get("username"):
                raw = f"{entry['username']}:{entry.get('password', '')}"
                token = base64.b64encode(raw.encode()).decode()
            if token:
                normalized = _normalise_host(host)
                self._auths[normalized] = token
                self._sources[normalized] = source

    def basic_for(self, registry: str) -> str | None:
        return self._auths.get(_normalise_host(registry))

    def list_entries(self) -> list[dict]:
        """Registries with stored credentials (username + source, never the secret)."""
        entries = []
        for host, token in sorted(self._auths.items()):
            username = None
            try:
                decoded = base64.b64decode(token).decode()
                username = decoded.split(":", 1)[0]
            except Exception:
                pass
            entries.append(
                {
                    "registry": host,
                    "username": username,
                    "source": self._sources.get(host, "mutable"),
                }
            )
        return entries

    @staticmethod
    def write_credential(config_path: str, registry: str, username: str, password: str) -> None:
        """Write registry credentials to a Docker config.json formatted file."""
        path = Path(config_path)
        data = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text()) or {}
            except (json.JSONDecodeError, OSError):
                data = {}

        if "auths" not in data:
            data["auths"] = {}

        raw = f"{username}:{password}"
        token = base64.b64encode(raw.encode()).decode()

        normalized = _normalise_host(registry)
        data["auths"][normalized] = {"auth": token}

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))

    @staticmethod
    def remove_credential(config_path: str, registry: str) -> bool:
        """Remove a registry's credential from the mutable config.json. Returns whether anything was removed."""
        path = Path(config_path)
        if not path.is_file():
            return False
        try:
            data = json.loads(path.read_text()) or {}
        except (json.JSONDecodeError, OSError):
            return False
        auths = data.get("auths") or {}
        normalized = _normalise_host(registry)
        removed = False
        for host in list(auths.keys()):
            if _normalise_host(host) == normalized:
                del auths[host]
                removed = True
        if removed:
            data["auths"] = auths
            path.write_text(json.dumps(data, indent=2))
        return removed


async def _probe_registry(host: str, basic: str | None) -> bool:
    """GET https://{host}/v2/, trying anonymous access then the given basic-auth token."""
    url = f"https://{host}/v2/"
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                return True
            if resp.status_code == 401:
                www_auth = resp.headers.get("WWW-Authenticate", "")
                if www_auth.lower().startswith("bearer "):
                    token = await _get_bearer_token(client, www_auth, basic)
                    if token:
                        resp2 = await client.get(url, headers={"Authorization": f"Bearer {token}"})
                        return resp2.status_code == 200
                    return False
                if basic:
                    resp2 = await client.get(url, headers={"Authorization": f"Basic {basic}"})
                    return resp2.status_code == 200
                return False
            return resp.status_code == 200
        except Exception:
            return False


async def verify_credentials(registry: str, username: str, password: str) -> bool:
    """Attempt to contact https://{registry}/v2/ with credentials to verify them."""
    host = _normalise_host(registry)
    raw = f"{username}:{password}"
    basic = base64.b64encode(raw.encode()).decode()
    return await _probe_registry(host, basic)


async def check_stored_auth(registry: str, basic_token: str | None) -> bool:
    """Re-validate an already-stored credential — used to show Valid/Invalid in the registry list."""
    if not basic_token:
        return False
    host = _normalise_host(registry)
    return await _probe_registry(host, basic_token)


def _normalise_host(host: str) -> str:
    for prefix in ("https://", "http://"):
        if host.startswith(prefix):
            host = host[len(prefix):]
    host = host.rstrip("/")
    # Docker config stores Hub as 'https://index.docker.io/v1/' — drop the path.
    host = host.split("/", 1)[0]
    # Treat all Docker Hub aliases the same.
    if host in {"index.docker.io", "docker.io", _DOCKER_HUB_HOST, "registry.docker.io"}:
        return _DOCKER_HUB_HOST
    return host


async def _get_bearer_token(
    client: httpx.AsyncClient, www_auth: str, basic: str | None
) -> str | None:
    """Follow a ``WWW-Authenticate: Bearer realm=...,service=...,scope=...``."""
    if not www_auth.lower().startswith("bearer "):
        return None
    params: dict[str, str] = {}
    for part in www_auth[len("bearer "):].split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            params[k.strip()] = v.strip().strip('"')
    realm = params.pop("realm", None)
    if not realm:
        return None
    headers = {"Authorization": f"Basic {basic}"} if basic else {}
    resp = await client.get(realm, params=params, headers=headers)
    resp.raise_for_status()
    body = resp.json()
    return body.get("token") or body.get("access_token")


async def get_remote_digest(
    ref: ImageRef, auth: RegistryAuth, *, client: httpx.AsyncClient | None = None
) -> tuple[str | None, bool]:
    """Return ``(digest, auth_required)`` for the tag's current registry digest.

    ``digest`` is ``None`` if it can't be resolved (network error, missing repo,
    unauthorized, etc.). ``auth_required`` is True when the registry rejected the
    request as unauthorized/forbidden even after trying any stored credential —
    a signal the caller can use to suggest a registry login.
    """
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=10.0, follow_redirects=True)
    url = f"https://{ref.registry}/v2/{ref.repository}/manifests/{ref.tag}"
    basic = auth.basic_for(ref.registry)
    auth_required = False
    try:
        headers = {"Accept": _ACCEPT}
        resp = await client.head(url, headers=headers)
        if resp.status_code == 401:
            token = await _get_bearer_token(
                client, resp.headers.get("WWW-Authenticate", ""), basic
            )
            if token:
                headers["Authorization"] = f"Bearer {token}"
            elif basic:
                headers["Authorization"] = f"Basic {basic}"
            resp = await client.head(url, headers=headers)
        if resp.status_code in (401, 403):
            auth_required = True
        if resp.status_code >= 400:
            # Some registries reject HEAD; retry with GET.
            resp = await client.get(url, headers=headers)
        if resp.status_code in (401, 403):
            auth_required = True
        elif resp.status_code < 400:
            auth_required = False
        if resp.status_code >= 400:
            return None, auth_required
        digest = resp.headers.get("Docker-Content-Digest")
        if digest:
            return digest.strip(), False
        # Fall back to hashing the manifest body if the header is absent.
        if resp.request.method == "GET" and resp.content:
            import hashlib

            return "sha256:" + hashlib.sha256(resp.content).hexdigest(), False
        return None, False
    except (httpx.HTTPError, ValueError):
        return None, False
    finally:
        if owns_client:
            await client.aclose()
