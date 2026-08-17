"""Overlay *fabric* probes — the low-level network state Docker never reports.

``netinspect.py`` answers "which containers does this node think are on which
network". This module answers the harder question: **is the plumbing under those
networks actually intact on this node?** It gathers four independent views that
the server correlates across nodes (see ``server/liteboard/nodes/fabric.py``):

``netns``
    Per overlay network, from inside that network's namespace: the VXLAN
    forwarding database (MAC -> destination VTEP) and the interface MTUs. A
    missing or wrong ``dst`` here silently blackholes traffic to an otherwise
    perfectly healthy container, and nothing logs it.
``root``
    Host-namespace links and addresses: underlay MTU (the transport an overlay
    is encapsulated into) and leftover ``vx-*`` interfaces from torn-down
    sandboxes, which make a node fail to rejoin its own network.
``service_table``
    Each overlay's service VIPs *as this node sees them*. Docker's embedded
    resolver answers from this table, so a node missing an entry its peers have
    can no longer resolve that service by name.
``swarm`` / ``dns``
    The local daemon's swarm state (a manager whose API bind failed keeps
    running, looking healthy from the outside) and whether a container on this
    node can resolve a public name at all.

Everything degrades to ``{"error": ...}`` per-probe rather than failing the
request: the namespace probes need ``CAP_SYS_ADMIN``/``CAP_NET_ADMIN`` and the
``/run/docker/netns`` mount, and a daemon without them must still serve the
Docker-API-only checks.
"""

from __future__ import annotations

import os
import socket
import threading
import urllib.parse

import netlink
from dockerapi import get as _docker_get

# Where Docker keeps its named network namespaces on the host, bind-mounted
# into the daemon container (see docker-compose.yml).
NETNS_DIR = os.environ.get("LITEBOARD_DOCKER_NETNS_DIR", "/host/docker-netns")
PROCFS = os.environ.get("LITEBOARD_PROCFS", "/proc")
# The host's root network namespace, bind-mounted straight in from
# /proc/1/ns/net. It has to arrive as its own mount rather than being read out
# of the mounted host procfs: opening /proc/<pid>/ns/* goes through the kernel's
# ptrace_may_access check, which denies even uid 0 in the container without
# CAP_SYS_PTRACE. Bind-mounting the nsfs inode sidesteps that check entirely,
# so the daemon needs no ptrace capability just to read the host's interfaces.
HOST_NETNS = os.environ.get("LITEBOARD_HOST_NETNS", "/host/netns/root")
# Public name used to check that containers on this node have working DNS
# egress. Set to an empty string to skip the probe entirely.
DNS_PROBE_HOST = os.environ.get("LITEBOARD_DNS_PROBE_HOST", "one.one.one.one")
DNS_PROBE_TIMEOUT = float(os.environ.get("LITEBOARD_DNS_PROBE_TIMEOUT", "5"))


def collect(socket_path: str = "/var/run/docker.sock") -> dict:
    """Gather every fabric probe. Never raises — failures are reported inline."""
    overlays = _overlay_networks(socket_path)
    return {
        "netns": _probe_netns(overlays),
        "root": _probe_root_netns(),
        "service_table": {net["id"]: net["service_table"] for net in overlays},
        "networks": [
            {k: net[k] for k in ("id", "name", "subnet", "mtu_option", "vxlan_ids", "attached")}
            for net in overlays
        ],
        "swarm": _probe_swarm(socket_path),
        "dns": _probe_dns(),
    }


# ---- repairs -------------------------------------------------------------- #
# Only failures with a *targeted, non-disruptive* fix are repairable from here.
# The desyncs that can only be cleared by restarting the engine (service_table)
# or by recreating a network (MTU) are reported with guidance instead — a button
# that bounces every container on a node is not a button worth having.
REPAIR_ACTIONS = ("fdb-replace", "delete-stale-vxlan")


def repair(action: str, params: dict) -> dict:
    """Apply one repair action. Returns ``{"ok": True}`` or ``{"error": ...}``."""
    if action == "fdb-replace":
        return _repair_fdb(params)
    if action == "delete-stale-vxlan":
        return _repair_stale_vxlan(params)
    return {"error": f"unknown action {action!r}"}


def _repair_fdb(params: dict) -> dict:
    """Rewrite one VXLAN FDB entry so it points at the node actually hosting it."""
    net_id = str(params.get("network") or "")
    mac = str(params.get("mac") or "").lower()
    dst = str(params.get("dst") or "")
    if not _valid_mac(mac):
        return {"error": f"invalid mac {mac!r}"}
    try:
        socket.inet_pton(socket.AF_INET, dst)
    except OSError:
        return {"error": f"invalid destination {dst!r}"}
    path = _netns_path(net_id)
    if not path:
        return {"error": f"no local namespace for network {net_id[:12]!r}"}

    def _apply() -> dict:
        vxlan = next((l for l in netlink.list_links() if l["kind"] == "vxlan"), None)
        if not vxlan:
            return {"error": "no vxlan interface in this namespace"}
        netlink.fdb_replace(vxlan["index"], mac, dst)
        return {"ok": True, "interface": vxlan["name"]}

    return netlink.in_netns(path, _apply)


def _repair_stale_vxlan(params: dict) -> dict:
    """Delete an orphaned host vxlan interface, re-checking staleness first.

    The state is re-verified *inside* the namespace at the moment of deletion
    rather than trusted from the report that produced the button — a device that
    came back up in the meantime must never be torn out from under a live
    network.
    """
    name = str(params.get("interface") or "")
    if not name or "/" in name:
        return {"error": f"invalid interface {name!r}"}
    ns_path = _host_netns_path()
    if not ns_path:
        return {"error": "host network namespace unreadable"}

    def _apply() -> dict:
        link = next((l for l in netlink.list_links() if l["name"] == name), None)
        if not link:
            return {"ok": True, "already_gone": True}
        if link["kind"] != "vxlan":
            return {"error": f"{name} is not a vxlan interface"}
        if link["up"] or link["master"] is not None:
            return {"error": f"{name} is in use (up or enslaved) — refusing to delete"}
        netlink.link_delete(link["index"])
        return {"ok": True, "deleted": name}

    return netlink.in_netns(ns_path, _apply)


def _valid_mac(mac: str) -> bool:
    parts = mac.split(":")
    return len(parts) == 6 and all(
        len(p) == 2 and all(c in "0123456789abcdef" for c in p) for p in parts
    )


# ---- docker-api views ----------------------------------------------------- #
def _overlay_networks(socket_path: str) -> list[dict]:
    """Every swarm overlay network this node participates in, with its service
    table (the VIP map Docker's embedded resolver answers from)."""
    try:
        raw = _docker_get("/networks", socket_path)
    except Exception:  # noqa: BLE001 - the caller reports an empty fabric view
        return []

    out = []
    for net in raw or []:
        if net.get("Driver") != "overlay":
            continue
        try:
            detail = _docker_get(
                f"/networks/{urllib.parse.quote(net['Id'])}?verbose=true", socket_path
            )
        except Exception:  # noqa: BLE001
            continue

        options = detail.get("Options") or {}
        ipam = (detail.get("IPAM") or {}).get("Config") or []
        vxlan_ids = [
            int(v)
            for v in (options.get("com.docker.network.driver.overlay.vxlanid_list") or "").split()
            if v.isdigit()
        ]
        mtu_option = options.get("com.docker.network.driver.mtu")

        # `verbose=true` returns this node's *local* copy of the service table.
        # A service present here on one node and absent on another is precisely
        # the NetworkDB service_table desync that breaks name resolution.
        services = {}
        for name, svc in (detail.get("Services") or {}).items():
            if not name:  # the unnamed pseudo-entry for the network itself
                continue
            services[name] = {
                "vip": svc.get("VIP") or None,
                "tasks": sorted(
                    t.get("EndpointIP") for t in (svc.get("Tasks") or []) if t.get("EndpointIP")
                ),
            }

        out.append(
            {
                "id": detail.get("Id"),
                "name": detail.get("Name"),
                "subnet": ipam[0].get("Subnet") if ipam else None,
                "mtu_option": int(mtu_option) if str(mtu_option).isdigit() else None,
                "vxlan_ids": vxlan_ids,
                "service_table": services,
                "attached": bool(detail.get("Containers")),
            }
        )
    return out


def _probe_swarm(socket_path: str) -> dict:
    """The local engine's swarm state.

    A manager that lost the race to bind its advertise address keeps running
    with a dead manager loop — ``docker info`` is the only place that says so.
    """
    try:
        info = _docker_get("/info", socket_path, timeout=8.0)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    swarm = (info or {}).get("Swarm") or {}
    return {
        "local_state": swarm.get("LocalNodeState"),
        "control_available": swarm.get("ControlAvailable"),
        "node_id": swarm.get("NodeID"),
        "node_addr": swarm.get("NodeAddr"),
        "managers": swarm.get("Managers"),
        "error": swarm.get("Error") or None,
    }


# ---- namespace probes ----------------------------------------------------- #
def _netns_path(net_id: str) -> str | None:
    """Locate the namespace file Docker created for an overlay network.

    Docker names them ``<n>-<first 10 chars of network id>`` (e.g.
    ``1-mur8fa5oyz``). Matching on the id rather than assuming the prefix keeps
    this working if the leading counter ever changes.
    """
    if not net_id:
        return None
    short = net_id[:10]
    try:
        entries = os.listdir(NETNS_DIR)
    except OSError:
        return None
    for entry in entries:
        _, _, suffix = entry.partition("-")
        if suffix == short:
            return os.path.join(NETNS_DIR, entry)
    return None


def _probe_netns(overlays: list[dict]) -> dict:
    """FDB + interface MTUs inside each overlay network's namespace."""
    if not os.path.isdir(NETNS_DIR):
        return {"error": f"{NETNS_DIR} not mounted (privileged probes disabled)"}

    out: dict[str, dict] = {}
    for net in overlays:
        path = _netns_path(net["id"])
        if not path:
            # Normal: a network with no local endpoint has no namespace here.
            continue
        out[net["id"]] = netlink.in_netns(path, _netns_probe)
    return out


def _netns_probe() -> dict:
    """Runs inside an overlay namespace (forked child). Read-only."""
    links = netlink.list_links()
    by_index = {link["index"]: link for link in links}
    fdb = []
    for entry in netlink.list_fdb():
        link = by_index.get(entry["ifindex"]) or {}
        if link.get("kind") != "vxlan":
            continue  # only the vxlan device carries VTEP destinations
        fdb.append({"mac": entry["mac"], "dst": entry["dst"], "self": entry["self"]})
    return {
        "links": [
            {"name": link["name"], "mtu": link["mtu"], "kind": link["kind"]}
            for link in links
            if link["name"] != "lo"
        ],
        "fdb": fdb,
    }


def _host_netns_path() -> str | None:
    """First host-netns path we can actually open.

    Probed by *opening* rather than with ``os.path.exists``: a namespace file we
    lack permission for reports as non-existent (``stat`` returns EACCES), which
    would otherwise be indistinguishable from one that was never mounted.
    """
    for path in (HOST_NETNS, os.path.join(PROCFS, "1", "ns", "net")):
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            continue
        os.close(fd)
        return path
    return None


def _probe_root_netns() -> dict:
    """Host-namespace links + addresses (underlay MTU, orphaned vxlan devices)."""
    ns_path = _host_netns_path()
    if not ns_path:
        return {
            "error": (
                f"host network namespace unreadable — bind-mount /proc/1/ns/net "
                f"to {HOST_NETNS} (reading it via {PROCFS} needs CAP_SYS_PTRACE)"
            )
        }
    return netlink.in_netns(ns_path, _root_probe)


def _root_probe() -> dict:
    """Runs inside the host root namespace (forked child). Read-only."""
    links = netlink.list_links()
    addrs = netlink.list_addrs()
    by_index: dict[int, list[str]] = {}
    for addr in addrs:
        by_index.setdefault(addr["index"], []).append(addr["addr"])
    return {
        "links": [
            {
                "name": link["name"],
                "mtu": link["mtu"],
                "kind": link["kind"],
                "up": link["up"],
                "operstate": link["operstate"],
                "master": link["master"],
                "vxlan_id": link["vxlan_id"],
                "addrs": by_index.get(link["index"], []),
            }
            for link in links
        ]
    }


# ---- dns egress ----------------------------------------------------------- #
def _probe_dns() -> dict:
    """Can a container on this node resolve a public name?

    Runs in a thread with a hard join deadline: a blackholed resolver fails by
    *timing out* (the failure mode we are looking for), and ``getaddrinfo``
    blocks in libc where no socket timeout applies.
    """
    resolvers = _resolvers()
    if not DNS_PROBE_HOST:
        return {"skipped": True, "resolvers": resolvers}

    result: dict = {}

    def _resolve() -> None:
        try:
            infos = socket.getaddrinfo(DNS_PROBE_HOST, None, socket.AF_INET)
            result["addresses"] = sorted({i[4][0] for i in infos})
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"{type(exc).__name__}: {exc}"

    thread = threading.Thread(target=_resolve, daemon=True)
    thread.start()
    thread.join(DNS_PROBE_TIMEOUT)
    if thread.is_alive():
        return {
            "host": DNS_PROBE_HOST,
            "ok": False,
            "error": f"timed out after {DNS_PROBE_TIMEOUT:g}s",
            "resolvers": resolvers,
        }
    return {
        "host": DNS_PROBE_HOST,
        "ok": "addresses" in result,
        "error": result.get("error"),
        "addresses": result.get("addresses"),
        "resolvers": resolvers,
    }


def _resolvers() -> list[str]:
    """Upstream resolvers this container was handed (dockerd copies the host's)."""
    out = []
    try:
        with open("/etc/resolv.conf", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "nameserver":
                    out.append(parts[1])
    except OSError:
        pass
    return out
