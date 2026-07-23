"""Local Docker image disk-usage + cleanup.

Reports how much space this node's images occupy and how much of that is
"unused" — not referenced by any container, running or stopped — the same
notion Docker uses for ``docker image prune -a``. The cleanup endpoint removes
exactly those unused images.
"""

from __future__ import annotations

import json
import urllib.parse

import dockerapi


def disk_usage(socket_path: str = "/var/run/docker.sock") -> dict:
    try:
        df = dockerapi.get("/system/df", socket_path)
    except Exception as exc:  # noqa: BLE001 - report, don't crash the daemon
        return {"error": str(exc)}

    images = df.get("Images") or []
    unused = [img for img in images if (img.get("Containers") or 0) <= 0]

    return {
        "image_count": len(images),
        "total_size": sum(img.get("Size") or 0 for img in images),
        "unused_count": len(unused),
        "unused_size": sum(img.get("Size") or 0 for img in unused),
    }


def prune_unused(socket_path: str = "/var/run/docker.sock") -> dict:
    """Remove every image not referenced by any container (``docker image
    prune -a`` equivalent). Returns what was deleted and space reclaimed."""
    filters = urllib.parse.quote(json.dumps({"dangling": ["false"]}))
    try:
        result = dockerapi.post(f"/images/prune?filters={filters}", socket_path)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    return {
        "deleted": len(result.get("ImagesDeleted") or []),
        "space_reclaimed": result.get("SpaceReclaimed", 0),
    }
