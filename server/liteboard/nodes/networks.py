"""Cross-node Docker network consistency analysis.

Each daemon reports its local view of the Docker networks and endpoint IPs it
sees. The server aggregates those views and flags genuine inconsistencies —
things redundancy alone can't explain:

* **ip-collision** — one IP claimed by two different containers on a network.
* **subnet-mismatch** — the same overlay network reported with different subnets
  on different nodes.
* **task-ip-conflict** — the *same* task slot (e.g. ``web.1``) observed with
  different IPs from different nodes (a stale/leaked endpoint, not redundancy).
* **service-ip-spread** — informational: IPs a service holds across the cluster.

Replicas of a service legitimately holding distinct IPs (``web.1`` vs ``web.2``)
are NOT flagged — only same-identity divergence is.
"""

from __future__ import annotations

from collections import defaultdict


def _task_identity(name: str) -> str | None:
    """``web.1.abcdef`` -> ``web.1`` (service + slot), stable across nodes."""
    if not name:
        return None
    parts = name.split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return parts[0]


def analyze_networks(networks_by_node: dict[str, dict]) -> dict:
    warnings: list[dict] = []

    # network name -> { node_id -> subnet }
    subnets_by_net: dict[str, dict[str, str]] = defaultdict(dict)
    # network name -> ip -> set of container identities
    ip_owners: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    # network name -> task identity -> { ip -> set(node) }
    task_ips: dict[str, dict[str, dict[str, set]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(set))
    )
    # service -> set of ips (across everything)
    service_ips: dict[str, set] = defaultdict(set)

    for node_id, view in (networks_by_node or {}).items():
        for net in (view or {}).get("networks", []):
            net_name = net.get("name") or net.get("id")
            if net.get("subnet"):
                subnets_by_net[net_name][node_id] = net["subnet"]
            for ep in net.get("endpoints", []):
                ip = ep.get("ipv4")
                if not ip:
                    continue
                identity = _task_identity(ep.get("name", ""))
                ip_owners[net_name][ip].add(identity or ep.get("container", "?"))
                if identity:
                    task_ips[net_name][identity][ip].add(node_id)
                if ep.get("service"):
                    service_ips[ep["service"]].add(ip)

    # --- ip collisions ---------------------------------------------------- #
    for net_name, ips in ip_owners.items():
        for ip, owners in ips.items():
            if len(owners) > 1:
                warnings.append(
                    {
                        "type": "ip-collision",
                        "severity": "critical",
                        "network": net_name,
                        "ip": ip,
                        "owners": sorted(o for o in owners if o),
                        "message": f"IP {ip} on {net_name} is claimed by "
                        f"{len(owners)} different containers.",
                    }
                )

    # --- subnet mismatches ------------------------------------------------ #
    for net_name, per_node in subnets_by_net.items():
        distinct = set(per_node.values())
        if len(distinct) > 1:
            warnings.append(
                {
                    "type": "subnet-mismatch",
                    "severity": "warning",
                    "network": net_name,
                    "subnets": sorted(distinct),
                    "message": f"Network {net_name} has differing subnets across "
                    f"nodes: {', '.join(sorted(distinct))}.",
                }
            )

    # --- same task, different IP across nodes ----------------------------- #
    for net_name, identities in task_ips.items():
        for identity, ips in identities.items():
            if len(ips) > 1:
                warnings.append(
                    {
                        "type": "task-ip-conflict",
                        "severity": "warning",
                        "network": net_name,
                        "task": identity,
                        "ips": sorted(ips.keys()),
                        "message": f"Task {identity} on {net_name} is seen with "
                        f"multiple IPs ({', '.join(sorted(ips.keys()))}); expected one.",
                    }
                )

    warnings.sort(key=lambda w: 0 if w["severity"] == "critical" else 1)

    return {
        "consistent": len(warnings) == 0,
        "warnings": warnings,
        "networks": [
            {"name": name, "nodes": len({n for n in nodes})}
            for name, nodes in ((n, subnets_by_net.get(n, {})) for n in ip_owners)
        ],
        "service_ips": {svc: sorted(ips) for svc, ips in service_ips.items()},
    }
