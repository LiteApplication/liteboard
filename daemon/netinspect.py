"""Local Docker network inspection.

Reports, per Docker network this node participates in, the containers attached
and the IPs they hold — annotated with the Swarm service they belong to. The
server collects these per-node views and flags cross-node inconsistencies (e.g.
the same service task showing different IPs where redundancy doesn't explain it).

Uses a tiny raw HTTP-over-unix-socket client so the daemon needs no Docker SDK.
"""

from __future__ import annotations

import http.client
import json
import socket
import urllib.parse


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float = 5.0) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:  # noqa: D401
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._socket_path)
        self.sock = sock


def _docker_get(path: str, socket_path: str) -> object:
    conn = _UnixHTTPConnection(socket_path)
    try:
        conn.request("GET", path, headers={"Host": "docker"})
        resp = conn.getresponse()
        data = resp.read()
        if resp.status >= 400:
            raise RuntimeError(f"docker api {path} -> {resp.status}: {data[:200]!r}")
        return json.loads(data)
    finally:
        conn.close()


def inspect_networks(socket_path: str = "/var/run/docker.sock") -> dict:
    """Return this node's view of overlay/bridge networks and endpoint IPs.

    Structure::

        {
          "networks": [
            {
              "id": "...", "name": "app_net", "scope": "swarm",
              "driver": "overlay", "subnet": "10.0.1.0/24",
              "endpoints": [
                {"container": "...", "name": "web.1.abc",
                 "service": "app_web", "task": "web.1.abc",
                 "ipv4": "10.0.1.5"}
              ]
            }
          ]
        }
    """
    networks = []
    try:
        raw_nets = _docker_get("/networks", socket_path)
    except Exception as exc:  # noqa: BLE001 - report, don't crash the daemon
        return {"networks": [], "error": str(exc)}

    for net in raw_nets or []:
        # Only networks with container endpoints on this node are interesting.
        detail = _docker_get(
            f"/networks/{urllib.parse.quote(net['Id'])}?verbose=false", socket_path
        )
        ipam = (detail.get("IPAM") or {}).get("Config") or []
        subnet = ipam[0].get("Subnet") if ipam else None

        endpoints = []
        for cid, ep in (detail.get("Containers") or {}).items():
            name = ep.get("Name", "")
            if name.endswith("-endpoint"):
                continue
            endpoints.append(
                {
                    "container": cid,
                    "name": name,
                    "service": _service_from_name(name),
                    "task": name,
                    "ipv4": (ep.get("IPv4Address") or "").split("/")[0] or None,
                    "ipv6": (ep.get("IPv6Address") or "").split("/")[0] or None,
                    "mac": ep.get("MacAddress"),
                }
            )

        if not endpoints:
            continue

        networks.append(
            {
                "id": detail.get("Id"),
                "name": detail.get("Name"),
                "scope": detail.get("Scope"),
                "driver": detail.get("Driver"),
                "subnet": subnet,
                "endpoints": endpoints,
            }
        )

    return {"networks": networks}


def _service_from_name(container_name: str) -> str | None:
    """Swarm task containers are named ``service.slot.taskid`` (or
    ``service.nodeid.taskid`` for global services). The service is the first
    dotted segment."""
    if not container_name:
        return None
    head = container_name.split(".", 1)[0]
    return head or None
