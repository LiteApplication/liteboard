"""Local Docker network inspection.

Reports, per Docker network this node participates in, the containers attached
and the IPs they hold — annotated with the Swarm service they belong to. The
server collects these per-node views and flags cross-node inconsistencies (e.g.
the same service task showing different IPs where redundancy doesn't explain it).

Uses a tiny raw HTTP-over-unix-socket client so the daemon needs no Docker SDK.
"""

from __future__ import annotations

import urllib.parse

from dockerapi import get as _docker_get


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
