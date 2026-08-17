"""Overlay fabric analysis — the failures Docker never reports.

``networks.py`` correlates *who is on which network*. This module correlates the
plumbing underneath, using the per-node probes from ``daemon/fabric.py``. Every
check here exists because the failure it detects is **silent**: the containers
are healthy, ``docker network inspect`` looks right, and the only symptom is
traffic that vanishes.

The checks, worst first:

``vxlan-fdb-desync``
    A node's VXLAN forwarding entry for a remote container has no destination
    VTEP, or points at the node that *used* to host it. Traffic to a healthy
    container is dropped by that one node — classically, one reverse-proxy
    replica 504s a route its peers serve fine. Repairable in place.
``overlay-mtu-oversize``
    The overlay's MTU plus VXLAN's 50-byte encapsulation exceeds the underlay
    the node actually routes over (a WireGuard/Tailscale mesh caps well below
    Ethernet). Small packets pass, large ones are silently lost — so every
    reachability test says "fine" while real traffic stalls.
``service-dns-desync``
    A node's copy of NetworkDB's service table is missing a VIP its peers have.
    Docker's embedded resolver answers from that table, so name lookups on that
    node NXDOMAIN and fall through to the *host's* upstream resolver — which may
    wildcard the name to a public IP.
``swarm-engine-degraded``
    The engine is up and the daemon answers, but its swarm module is dead —
    e.g. a manager that lost the boot race to bind its advertise address and
    never retried. Nothing crashes; the node just stops participating.
``stale-vxlan-iface``
    Debris in the host namespace from a torn-down sandbox, which makes the node
    fail to recreate that interface ("file exists") and drop off the network.
    Repairable in place.
``dns-egress-blackhole``
    Containers on the node cannot resolve public names at all.
"""

from __future__ import annotations

from collections import defaultdict

# VXLAN adds outer IP (20) + UDP (8) + VXLAN (8) + inner Ethernet (14).
VXLAN_OVERHEAD = 50

_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}

# Interface name prefixes that are never the underlay transport — virtual
# plumbing Docker or the container runtime created.
_VIRTUAL_PREFIXES = ("lo", "docker", "br-", "veth", "vx-", "virbr", "vxlan")


def _mac_to_ip(mac: str) -> str | None:
    """``02:42:0a:00:01:3d`` -> ``10.0.1.61``.

    Docker derives overlay MAC addresses straight from the IPv4 address, which
    is what lets a forwarding-table entry (which only knows MACs) be matched
    against task placement (which only knows IPs).
    """
    parts = (mac or "").lower().split(":")
    if len(parts) != 6 or parts[0] != "02" or parts[1] != "42":
        return None
    try:
        return ".".join(str(int(p, 16)) for p in parts[2:])
    except ValueError:
        return None


def analyze_fabric(
    fabric_by_node: dict[str, dict],
    nodes: list[dict],
    task_endpoints: list[dict],
) -> dict:
    """Correlate every node's fabric probe into a ranked finding list."""
    by_id = {n["id"]: n for n in nodes}
    # The VTEP a peer must forward to is the node's advertised swarm address.
    addr_by_node = {
        n["id"]: (n.get("addr") or "").split(":")[0] for n in nodes if n.get("addr")
    }
    findings: list[dict] = []
    probes: list[dict] = []

    # ip -> node that actually hosts it, per network. Ground truth for the FDB.
    owner: dict[tuple[str, str], str] = {
        (ep["network_id"], ep["ip"]): ep["node_id"]
        for ep in task_endpoints
        if ep.get("node_id")
    }
    net_names = {ep["network_id"]: ep.get("network") for ep in task_endpoints}

    for node_id, report in (fabric_by_node or {}).items():
        node = by_id.get(node_id) or {"id": node_id, "hostname": node_id}
        if not report or "_error" in report:
            probes.append(
                {
                    "node": node.get("hostname"),
                    "node_id": node_id,
                    "reachable": False,
                    "error": (report or {}).get("_error", "no data"),
                }
            )
            continue

        for net in report.get("networks") or []:
            if net.get("id") and net.get("name"):
                net_names.setdefault(net["id"], net["name"])

        findings += _check_fdb(node, report, owner, addr_by_node, net_names)
        findings += _check_mtu(node, report, net_names)
        findings += _check_swarm(node, report)
        findings += _check_stale_vxlan(node, report)
        findings += _check_dns(node, report)

        probes.append(
            {
                "node": node.get("hostname"),
                "node_id": node_id,
                "reachable": True,
                "namespaces": _probe_status(report.get("netns")),
                "root_namespace": _probe_status(report.get("root")),
                "networks": len(report.get("networks") or []),
            }
        )

    findings += _check_service_table(fabric_by_node, by_id, net_names)

    findings.sort(key=lambda f: (_SEVERITY_ORDER.get(f["severity"], 3), f["type"]))
    return {
        "healthy": not findings,
        "findings": findings,
        "probes": sorted(probes, key=lambda p: p.get("node") or ""),
    }


def _probe_status(section: object) -> str:
    if isinstance(section, dict) and "error" in section:
        return f"unavailable: {section['error']}"
    return "ok" if section else "no data"


# ---- checks --------------------------------------------------------------- #
def _check_fdb(
    node: dict,
    report: dict,
    owner: dict[tuple[str, str], str],
    addr_by_node: dict[str, str],
    net_names: dict[str, str | None],
) -> list[dict]:
    """VXLAN forwarding entries vs. where the tasks actually run."""
    netns = report.get("netns") or {}
    if "error" in netns:
        return []

    out = []
    for net_id, view in netns.items():
        if not isinstance(view, dict) or "error" in view:
            continue
        # One MAC yields two entries: the bridge's learned one and the vxlan
        # "self" one that carries the destination. Only the latter routes.
        self_dst: dict[str, str | None] = {}
        seen: set[str] = set()
        for entry in view.get("fdb") or []:
            seen.add(entry["mac"])
            if entry.get("self"):
                self_dst[entry["mac"]] = entry.get("dst")

        for mac in sorted(seen):
            ip = _mac_to_ip(mac)
            if not ip:
                continue
            owner_id = owner.get((net_id, ip))
            # Unknown IPs are stale entries for containers that no longer exist,
            # and entries for our own containers never traverse the vxlan.
            if not owner_id or owner_id == node["id"]:
                continue
            expected = addr_by_node.get(owner_id)
            if not expected:
                continue
            actual = self_dst.get(mac)
            if actual == expected:
                continue

            net_name = net_names.get(net_id) or net_id[:12]
            if actual is None:
                message = (
                    f"{node['hostname']} has no forwarding destination for {ip} on "
                    f"{net_name}; traffic to it is silently dropped."
                )
            else:
                message = (
                    f"{node['hostname']} forwards {ip} on {net_name} to {actual}, but "
                    f"the container now runs on {expected}."
                )
            out.append(
                {
                    "type": "vxlan-fdb-desync",
                    "severity": "critical",
                    "node": node["hostname"],
                    "node_id": node["id"],
                    "network": net_name,
                    "message": message,
                    "detail": {"mac": mac, "ip": ip, "current_dst": actual, "expected_dst": expected},
                    "hint": (
                        "A NetworkDB gossip race left this node's forwarding table stale. "
                        "Repairing rewrites the single entry — no container restarts."
                    ),
                    "repair": {
                        "action": "fdb-replace",
                        "label": "Repair route",
                        "params": {"network": net_id, "mac": mac, "dst": expected},
                    },
                }
            )
    return out


def _check_mtu(node: dict, report: dict, net_names: dict[str, str | None]) -> list[dict]:
    """Overlay MTU vs. the underlay this node actually routes over."""
    root = report.get("root") or {}
    netns = report.get("netns") or {}
    if "error" in root or "error" in netns:
        return []

    underlay = _underlay_link(root.get("links") or [], node.get("addr"))
    if not underlay or not underlay.get("mtu"):
        return []

    out = []
    for net_id, view in netns.items():
        if not isinstance(view, dict) or "error" in view:
            continue
        mtus = [l["mtu"] for l in view.get("links") or [] if l.get("mtu")]
        if not mtus:
            continue
        overlay_mtu = max(mtus)
        encapsulated = overlay_mtu + VXLAN_OVERHEAD
        if encapsulated <= underlay["mtu"]:
            continue
        net_name = net_names.get(net_id) or net_id[:12]
        out.append(
            {
                "type": "overlay-mtu-oversize",
                "severity": "critical",
                "node": node["hostname"],
                "node_id": node["id"],
                "network": net_name,
                "message": (
                    f"{net_name} runs at MTU {overlay_mtu}; encapsulated that is "
                    f"{encapsulated} bytes, over {underlay['name']}'s {underlay['mtu']}."
                ),
                "detail": {
                    "overlay_mtu": overlay_mtu,
                    "encapsulated": encapsulated,
                    "underlay": underlay["name"],
                    "underlay_mtu": underlay["mtu"],
                    "recommended_mtu": underlay["mtu"] - VXLAN_OVERHEAD,
                },
                "hint": (
                    "Large packets are silently dropped while small ones pass, so "
                    "reachability tests look clean. MTU is immutable once a network "
                    f"exists: recreate it with driver option "
                    f"com.docker.network.driver.mtu={underlay['mtu'] - VXLAN_OVERHEAD}."
                ),
                "repair": None,  # requires recreating the network — never automatic
            }
        )
    return out


def _underlay_link(links: list[dict], node_addr: str | None) -> dict | None:
    """The interface carrying this node's swarm traffic.

    Matched by the node's advertised address rather than guessed from names —
    on a mesh-VPN cluster the transport is a tunnel device with an MTU far below
    the physical NIC sitting next to it, and picking the wrong one inverts the
    result of the MTU check.
    """
    addr = (node_addr or "").split(":")[0]
    if addr:
        for link in links:
            if addr in (link.get("addrs") or []):
                return link
    candidates = [
        link
        for link in links
        if link.get("mtu")
        and link.get("up")
        and not link["name"].startswith(_VIRTUAL_PREFIXES)
    ]
    return min(candidates, key=lambda l: l["mtu"]) if candidates else None


def _check_service_table(
    fabric_by_node: dict[str, dict],
    by_id: dict[str, dict],
    net_names: dict[str, str | None],
) -> list[dict]:
    """A node missing service VIPs that its peers agree on."""
    # network -> service -> {node_id: vip}
    seen: dict[str, dict[str, dict[str, str | None]]] = defaultdict(lambda: defaultdict(dict))
    participants: dict[str, set[str]] = defaultdict(set)

    for node_id, report in (fabric_by_node or {}).items():
        if not report or "_error" in report:
            continue
        table = report.get("service_table") or {}
        for net in report.get("networks") or []:
            net_id = net.get("id")
            if not net_id or not net.get("attached"):
                continue
            participants[net_id].add(node_id)
            for name, svc in (table.get(net_id) or {}).items():
                seen[net_id][name][node_id] = (svc or {}).get("vip")

    out = []
    for net_id, services in seen.items():
        members = participants.get(net_id, set())
        # A quorum of two keeps a single desynced node from looking authoritative.
        if len(members) < 2:
            continue
        net_name = net_names.get(net_id) or net_id[:12]
        for name, per_node in services.items():
            present = set(per_node)
            if len(present) < 2:
                continue  # too thin to call anyone wrong
            for node_id in sorted(members - present):
                node = by_id.get(node_id) or {"id": node_id, "hostname": node_id}
                out.append(
                    {
                        "type": "service-dns-desync",
                        "severity": "critical",
                        "node": node["hostname"],
                        "node_id": node_id,
                        "network": net_name,
                        "message": (
                            f"{node['hostname']} is missing the service entry for "
                            f"{name} on {net_name} that {len(present)} other nodes have; "
                            "name lookups for it fail on this node."
                        ),
                        "detail": {"service": name, "known_by": sorted(
                            (by_id.get(n) or {}).get("hostname", n) for n in present
                        )},
                        "hint": (
                            "NetworkDB's service table desynced here. Bouncing the "
                            "affected containers does not clear it — restart the Docker "
                            f"daemon on {node['hostname']}."
                        ),
                        "repair": None,  # only a daemon restart clears this
                    }
                )

            vips = {v for v in per_node.values() if v}
            if len(vips) > 1:
                out.append(
                    {
                        "type": "service-dns-desync",
                        "severity": "warning",
                        "node": None,
                        "node_id": None,
                        "network": net_name,
                        "message": (
                            f"Nodes disagree on the VIP for {name} on {net_name}: "
                            f"{', '.join(sorted(vips))}."
                        ),
                        "detail": {
                            "service": name,
                            "vips": {
                                (by_id.get(n) or {}).get("hostname", n): v
                                for n, v in per_node.items()
                            },
                        },
                        "hint": "Restart the Docker daemon on the node holding the stale VIP.",
                        "repair": None,
                    }
                )
    return out


def _check_swarm(node: dict, report: dict) -> list[dict]:
    """The engine answers, but is it still part of the swarm?"""
    swarm = report.get("swarm") or {}
    if "error" not in swarm and not swarm:
        return []
    state = swarm.get("local_state")
    error = swarm.get("error")
    if not error and state in {"active", None}:
        return []
    return [
        {
            "type": "swarm-engine-degraded",
            "severity": "critical",
            "node": node["hostname"],
            "node_id": node["id"],
            "network": None,
            "message": (
                f"{node['hostname']} is reachable but its engine reports swarm state "
                f"'{state or 'unknown'}'" + (f": {error}" if error else ".")
            ),
            "detail": {"local_state": state, "engine_error": error},
            "hint": (
                "The engine keeps running with a dead swarm module — commonly a manager "
                "that raced its network interface at boot and never retried the bind. "
                f"Restart the Docker daemon on {node['hostname']}."
            ),
            "repair": None,  # needs host-level control the daemon deliberately lacks
        }
    ]


def _check_stale_vxlan(node: dict, report: dict) -> list[dict]:
    """Orphaned vxlan devices in the host namespace."""
    root = report.get("root") or {}
    if "error" in root:
        return []
    known_vnis = {
        vni for net in (report.get("networks") or []) for vni in (net.get("vxlan_ids") or [])
    }

    out = []
    for link in root.get("links") or []:
        if link.get("kind") != "vxlan" or link.get("up") or link.get("master") is not None:
            continue
        vni = link.get("vxlan_id")
        out.append(
            {
                "type": "stale-vxlan-iface",
                "severity": "warning",
                "node": node["hostname"],
                "node_id": node["id"],
                "network": None,
                "message": (
                    f"{node['hostname']} has an orphaned vxlan interface {link['name']}"
                    + (f" (VNI {vni}, still in use by a live network)" if vni in known_vnis else "")
                    + "."
                ),
                "detail": {"interface": link["name"], "vxlan_id": vni, "operstate": link.get("operstate")},
                "hint": (
                    "Left over from a torn-down sandbox. While it exists the node fails "
                    "to recreate that interface ('file exists') and cannot rejoin the "
                    "network; Docker retries on its own once it is gone."
                ),
                "repair": {
                    "action": "delete-stale-vxlan",
                    "label": "Delete interface",
                    "params": {"interface": link["name"]},
                },
            }
        )
    return out


def _check_dns(node: dict, report: dict) -> list[dict]:
    """Can containers on this node resolve public names?"""
    dns = report.get("dns") or {}
    if dns.get("skipped") or dns.get("ok") is not False:
        return []
    return [
        {
            "type": "dns-egress-blackhole",
            "severity": "warning",
            "node": node["hostname"],
            "node_id": node["id"],
            "network": None,
            "message": (
                f"Containers on {node['hostname']} cannot resolve public names "
                f"({dns.get('host')}: {dns.get('error')})."
            ),
            "detail": {"resolvers": dns.get("resolvers"), "error": dns.get("error")},
            "hint": (
                "The resolvers dockerd hands to containers are unreachable from this "
                "host — often a VPN kill switch dropping the DHCP-supplied ones. Pin "
                "working resolvers in /etc/docker/daemon.json, or keep workloads on "
                "this node to in-cluster service names."
            ),
            "repair": None,  # host network configuration, not ours to change
        }
    ]
