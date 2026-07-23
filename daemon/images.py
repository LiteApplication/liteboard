"""Local Docker image disk-usage + cleanup.

Reports how much space this node's images occupy and how much of that is
"unused" — not referenced by any container, running or stopped — the same
notion Docker uses for ``docker image prune -a``.

Counting deliberately avoids ``GET /system/df``: that endpoint makes the
Docker daemon recompute real on-disk usage across every image/container/
volume layer, which is slow and drives dockerd CPU/IO hard, especially when
polled repeatedly. ``/images/json`` + ``/containers/json`` give the same
counts from data Docker already has cached, no disk walk required.

Pruning removes images one at a time (rather than the bulk ``/images/prune``
endpoint) so progress can be reported while it runs instead of blocking the
caller until the whole cleanup finishes.
"""

from __future__ import annotations

import threading
import time
import uuid

import dockerapi

# Counting is cheap; give it a little more slack than the default 5s anyway
# since it still crosses the docker socket.
_LIST_TIMEOUT = 10.0
# A single image delete is normally fast, but layer removal can occasionally
# stall; keep a generous per-call budget without blocking the whole job.
_DELETE_TIMEOUT = 30.0

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _unused_images(socket_path: str) -> list[dict]:
    images_list = dockerapi.get("/images/json", socket_path, timeout=_LIST_TIMEOUT) or []
    containers = (
        dockerapi.get("/containers/json?all=true", socket_path, timeout=_LIST_TIMEOUT) or []
    )
    used_ids = {c.get("ImageID") for c in containers if c.get("ImageID")}
    return [img for img in images_list if img.get("Id") not in used_ids]


def disk_usage(socket_path: str = "/var/run/docker.sock") -> dict:
    try:
        images_list = dockerapi.get("/images/json", socket_path, timeout=_LIST_TIMEOUT) or []
        containers = (
            dockerapi.get("/containers/json?all=true", socket_path, timeout=_LIST_TIMEOUT) or []
        )
    except Exception as exc:  # noqa: BLE001 - report, don't crash the daemon
        return {"error": str(exc)}

    used_ids = {c.get("ImageID") for c in containers if c.get("ImageID")}
    total_size = 0
    unused_count = 0
    unused_size = 0
    for img in images_list:
        size = img.get("Size") or 0
        total_size += size
        if img.get("Id") not in used_ids:
            unused_count += 1
            unused_size += size

    return {
        "image_count": len(images_list),
        "total_size": total_size,
        "unused_count": unused_count,
        "unused_size": unused_size,
    }


def start_prune(socket_path: str = "/var/run/docker.sock") -> str:
    """Kick off a background prune job and return its job id immediately."""
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "total": 0,
            "done": 0,
            "deleted": 0,
            "space_reclaimed": 0,
            "started_at": time.time(),
        }
    threading.Thread(target=_run_prune, args=(job_id, socket_path), daemon=True).start()
    return job_id


def _run_prune(job_id: str, socket_path: str) -> None:
    def update(**kw):
        with _jobs_lock:
            _jobs[job_id].update(kw)

    try:
        unused = _unused_images(socket_path)
    except Exception as exc:  # noqa: BLE001
        update(status="error", error=str(exc))
        return

    update(total=len(unused))
    for img in unused:
        image_id = img.get("Id")
        try:
            result = dockerapi.delete(
                f"/images/{image_id}?force=false", socket_path, timeout=_DELETE_TIMEOUT
            )
            if any("Deleted" in item for item in (result or []) if isinstance(item, dict)):
                with _jobs_lock:
                    _jobs[job_id]["deleted"] += 1
                    _jobs[job_id]["space_reclaimed"] += img.get("Size") or 0
        except Exception:  # noqa: BLE001 - keep going; e.g. image already gone / in use
            pass
        with _jobs_lock:
            _jobs[job_id]["done"] += 1

    update(status="done")


def job_status(job_id: str) -> dict:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return {"error": "job not found"}
        return dict(job)
