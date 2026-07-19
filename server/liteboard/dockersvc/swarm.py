"""Thin wrapper over docker-py for the Swarm data LiteBoard needs."""

from __future__ import annotations

import copy
import threading
from functools import lru_cache

import docker
from docker import DockerClient

from ..config import get_settings

# Service label the compose stack stamps on the daemon service so the server
# can find it to inject the signing public key.
DAEMON_SERVICE_LABEL = "liteboard.role=daemon"
_PUBKEY_ENV = "LITEBOARD_SERVER_PUBKEY"


@lru_cache
def get_client() -> DockerClient:
    settings = get_settings()
    return docker.DockerClient(base_url=settings.docker_host)


_lock = threading.Lock()


def list_nodes() -> list[dict]:
    """Return swarm nodes as plain dicts with the fields we care about."""
    client = get_client()
    nodes = []
    for node in client.nodes.list():
        attrs = node.attrs
        desc = attrs.get("Description", {})
        status = attrs.get("Status", {})
        spec = attrs.get("Spec", {})
        nodes.append(
            {
                "id": node.id,
                "hostname": desc.get("Hostname"),
                "role": spec.get("Role"),
                "availability": spec.get("Availability"),
                "state": status.get("State"),
                "addr": status.get("Addr"),
                "leader": (attrs.get("ManagerStatus") or {}).get("Leader", False),
                "engine_version": (desc.get("Engine") or {}).get("EngineVersion"),
                "platform": desc.get("Platform", {}),
                "resources": desc.get("Resources", {}),
            }
        )
    return nodes


def list_services_with_tasks() -> list[dict]:
    """Return each service joined with its tasks (raw dicts)."""
    client = get_client()
    out = []
    for svc in client.services.list():
        attrs = svc.attrs
        spec = attrs.get("Spec", {})
        mode = spec.get("Mode", {})
        tasks = svc.tasks()  # all tasks incl. historical
        out.append(
            {
                "id": svc.id,
                "name": spec.get("Name"),
                "labels": spec.get("Labels", {}),
                "mode": mode,
                "image": (
                    spec.get("TaskTemplate", {})
                    .get("ContainerSpec", {})
                    .get("Image", "")
                ),
                "update_status": attrs.get("UpdateStatus"),
                "created_at": attrs.get("CreatedAt"),
                "updated_at": attrs.get("UpdatedAt"),
                "tasks": tasks,
            }
        )
    return out


def update_service_image(service_id: str, image_ref: str) -> None:
    """Update a service to a new image ref (may be pinned with @sha256)."""
    client = get_client()
    with _lock:
        svc = client.services.get(service_id)
        svc.update(image=image_ref, force_update=None)


def find_daemon_service():
    """Locate the LiteBoard daemon service (by its stack label, name fallback)."""
    client = get_client()
    labelled = client.services.list(filters={"label": DAEMON_SERVICE_LABEL})
    if labelled:
        return labelled[0]
    for svc in client.services.list():
        name = svc.attrs.get("Spec", {}).get("Name", "") or ""
        if name == "daemon" or name.endswith("_daemon"):
            return svc
    return None


def ensure_daemon_pubkey(pub_b64: str) -> str:
    """Ensure the daemon service env carries the server's signing public key.

    Returns ``"updated"``, ``"ok"`` (already correct), or ``"not-found"``.

    docker-py's ``Service.update`` only preserves the image and drops every
    other field, so we drive the low-level ``update_service`` with the existing
    spec and change *only* the ``LITEBOARD_SERVER_PUBKEY`` env entry.
    """
    client = get_client()
    with _lock:
        svc = find_daemon_service()
        if svc is None:
            return "not-found"
        spec = copy.deepcopy(svc.attrs.get("Spec", {}))
        task = spec.setdefault("TaskTemplate", {})
        cspec = task.setdefault("ContainerSpec", {})
        env = list(cspec.get("Env") or [])
        target = f"{_PUBKEY_ENV}={pub_b64}"
        current = next((e for e in env if e.startswith(f"{_PUBKEY_ENV}=")), None)
        if current == target:
            return "ok"
        env = [e for e in env if not e.startswith(f"{_PUBKEY_ENV}=")]
        env.append(target)
        cspec["Env"] = env
        # fetch_current_spec=True: docker-py re-reads the live spec and merges
        # our TaskTemplate over it, so we change *only* the env and preserve
        # everything else (mounts, networks, placement, restart policy, …).
        client.api.update_service(
            svc.id,
            svc.version,
            task_template=task,
            fetch_current_spec=True,
        )
        return "updated"


def force_update_service(service_id: str) -> None:
    client = get_client()
    with _lock:
        svc = client.services.get(service_id)
        svc.force_update()


def _demux_log_stream(raw: bytes) -> str:
    """Decode a (possibly multiplexed) Docker log stream to text.

    Swarm service logs come back framed like container logs when there is no
    TTY: each chunk is prefixed with an 8-byte header ``[stream, 0, 0, 0,
    size(4, big-endian)]``. If the payload doesn't look framed we decode it
    verbatim.
    """
    if not raw:
        return ""
    framed = len(raw) >= 8 and raw[0] in (0, 1, 2) and raw[1:4] == b"\x00\x00\x00"
    if not framed:
        return raw.decode("utf-8", "replace")

    out: list[str] = []
    i, n = 0, len(raw)
    while i + 8 <= n:
        header = raw[i : i + 8]
        if header[0] not in (0, 1, 2) or header[1:4] != b"\x00\x00\x00":
            out.append(raw[i:].decode("utf-8", "replace"))  # not a valid frame
            break
        size = int.from_bytes(header[4:8], "big")
        i += 8
        out.append(raw[i : i + size].decode("utf-8", "replace"))
        i += size
    return "".join(out)


def service_logs(service_id: str, tail: int = 5000) -> dict:
    """Return the logs of a service's most recent task ("last session").

    For a crash-looping service this is the run that just crashed: we scope the
    stream to ``since`` the newest task's creation time so older, already-dead
    sessions are excluded, and read up to ``tail`` lines from that point.
    """
    from .health import _parse_ts  # local import: avoid a module import cycle

    client = get_client()
    with _lock:
        svc = client.services.get(service_id)
        name = svc.attrs.get("Spec", {}).get("Name")
        tasks = svc.tasks()
        started = None
        if tasks:
            latest = max(tasks, key=lambda t: t.get("CreatedAt") or "")
            started = _parse_ts(latest.get("CreatedAt"))
        kwargs = dict(stdout=True, stderr=True, timestamps=True, tail=tail)
        if started is not None:
            # `since` is a UNIX timestamp (int); back off a couple of seconds so
            # the very first lines of the session aren't clipped.
            kwargs["since"] = int(started.timestamp()) - 2
        raw = svc.logs(**kwargs)

    if hasattr(raw, "read"):  # stream object
        raw = raw.read()
    elif not isinstance(raw, (bytes, bytearray)):  # generator of chunks
        raw = b"".join(raw)

    return {
        "service": name,
        "logs": _demux_log_stream(bytes(raw)).rstrip("\n"),
        "since": started.isoformat() if started else None,
    }


def join_info() -> dict:
    """Return swarm join tokens + manager address(es) for bootstrapping a node.

    A new node only needs to *join the swarm* — the LiteBoard daemon is a
    ``global`` service and deploys onto it automatically.
    """
    client = get_client()
    swarm = client.swarm.attrs
    tokens = swarm.get("JoinTokens", {}) or {}
    info = client.info()
    remote_managers = (info.get("Swarm") or {}).get("RemoteManagers") or []
    addrs = [m.get("Addr") for m in remote_managers if m.get("Addr")]
    return {
        "worker_token": tokens.get("Worker"),
        "manager_token": tokens.get("Manager"),
        "manager_addrs": addrs,
    }


def swarm_info() -> dict:
    client = get_client()
    info = client.info()
    swarm = info.get("Swarm", {})
    return {
        "node_id": swarm.get("NodeID"),
        "nodes": swarm.get("Nodes"),
        "managers": swarm.get("Managers"),
        "cluster_id": (swarm.get("Cluster") or {}).get("ID"),
    }
