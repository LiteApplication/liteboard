"""Detect out-of-date service images and apply updates.

For each service, compare the digest it is currently running (Swarm pins the
resolved ``repo:tag@sha256:...`` into the service spec) against the digest the
registry currently serves for that tag. If they differ, an update is available;
applying it re-pins the service to the new digest for a deterministic rollout.
"""

from __future__ import annotations

import asyncio

import httpx

from ..config import get_settings
from ..registry.manifest import RegistryAuth, get_remote_digest, parse_image_ref
from . import swarm


def _split_digest(image: str) -> tuple[str, str | None]:
    """Return (repo:tag, digest) from a possibly-pinned image reference."""
    if "@" in image:
        base, digest = image.split("@", 1)
        return base, digest
    return image, None


async def _check_one(
    service: dict, auth: RegistryAuth, client: httpx.AsyncClient
) -> dict:
    image = service["image"]
    base, running_digest = _split_digest(image)
    ref = parse_image_ref(image)
    remote_digest = await get_remote_digest(ref, auth, client=client)

    if remote_digest is None:
        status = "unknown"
        update_available = False
    elif running_digest is None:
        # No pinned digest to compare against — surface the remote digest but
        # don't claim an update since we can't prove drift.
        status = "unpinned"
        update_available = False
    elif running_digest != remote_digest:
        status = "outdated"
        update_available = True
    else:
        status = "current"
        update_available = False

    return {
        "id": service["id"],
        "name": service["name"],
        "image": base,
        "registry": ref.registry,
        "repository": ref.repository,
        "tag": ref.tag,
        "running_digest": running_digest,
        "remote_digest": remote_digest,
        "status": status,
        "update_available": update_available,
    }


async def check_updates(services: list[dict]) -> list[dict]:
    settings = get_settings()
    auth = RegistryAuth(settings.registry_config_file)
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        results = await asyncio.gather(
            *(_check_one(s, auth, client) for s in services)
        )
    results.sort(key=lambda r: (not r["update_available"], r["name"]))
    return list(results)


def apply_update(service_id: str, repository: str, tag: str, registry: str, digest: str) -> None:
    """Pin the service to ``repo:tag@digest``. Registry host is preserved."""
    from ..registry.manifest import _DOCKER_HUB_HOST

    prefix = "" if registry == _DOCKER_HUB_HOST else f"{registry}/"
    repo = repository
    if registry == _DOCKER_HUB_HOST and repo.startswith("library/"):
        repo = repo[len("library/"):]
    image_ref = f"{prefix}{repo}:{tag}@{digest}"
    swarm.update_service_image(service_id, image_ref)
