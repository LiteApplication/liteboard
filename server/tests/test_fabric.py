"""Overlay fabric analysis — the silent-failure checks.

Each of these mirrors a failure that produced no log line anywhere: a healthy
container that one node can't reach, a network whose large packets vanish, a
node whose resolver forgot a service. The analysis is the only thing standing
between those and an afternoon of tcpdump, so it gets tested against synthetic
probe payloads rather than a live swarm.
"""

from __future__ import annotations

from liteboard.nodes.fabric import _mac_to_ip, analyze_fabric

NET = "mur8fa5oyzabc123"
NODES = [
    {"id": "nA", "hostname": "alpha", "addr": "100.64.0.1"},
    {"id": "nB", "hostname": "beta", "addr": "100.64.0.2"},
    {"id": "nC", "hostname": "gamma", "addr": "100.64.0.3"},
]
# A task on beta, which alpha must therefore forward to 100.64.0.2.
ENDPOINTS = [{"node_id": "nB", "network_id": NET, "ip": "10.0.1.61", "network": "app"}]
REMOTE_MAC = "02:42:0a:00:01:3d"  # == 10.0.1.61


def _report(*, fdb=None, links=None, root_links=None, service_table=None, swarm=None, dns=None):
    """A healthy single-network probe payload, with overrides."""
    return {
        "networks": [
            {
                "id": NET,
                "name": "app",
                "subnet": "10.0.1.0/24",
                "mtu_option": 1230,
                "vxlan_ids": [4097],
                "attached": True,
            }
        ],
        "netns": {
            NET: {
                "links": links if links is not None else [{"name": "vxlan0", "mtu": 1230, "kind": "vxlan"}],
                "fdb": fdb if fdb is not None else [{"mac": REMOTE_MAC, "dst": "100.64.0.2", "self": True}],
            }
        },
        "root": {
            "links": root_links
            if root_links is not None
            else [
                {
                    "name": "tailscale0",
                    "mtu": 1280,
                    "kind": None,
                    "up": True,
                    "operstate": "up",
                    "master": None,
                    "vxlan_id": None,
                    "addrs": ["100.64.0.1"],
                }
            ]
        },
        "service_table": service_table
        if service_table is not None
        else {NET: {"socket-proxy": {"vip": "10.0.2.11", "tasks": []}}},
        "swarm": swarm if swarm is not None else {"local_state": "active", "error": None},
        "dns": dns if dns is not None else {"ok": True, "host": "one.one.one.one"},
    }


def _types(result):
    return [f["type"] for f in result["findings"]]


def test_mac_to_ip_round_trips_docker_overlay_encoding():
    assert _mac_to_ip("02:42:0a:00:01:3d") == "10.0.1.61"
    assert _mac_to_ip("02:42:ff:ff:ff:ff") == "255.255.255.255"
    # Not a Docker-derived overlay MAC — must not be guessed at.
    assert _mac_to_ip("aa:bb:cc:dd:ee:ff") is None
    assert _mac_to_ip("") is None


def test_healthy_fabric_reports_nothing():
    result = analyze_fabric({"nA": _report()}, NODES, ENDPOINTS)
    assert result["healthy"] is True
    assert result["findings"] == []


def test_missing_vtep_is_flagged_and_repairable():
    """The blackhole case: the entry exists but carries no destination."""
    report = _report(fdb=[{"mac": REMOTE_MAC, "dst": None, "self": True}])
    result = analyze_fabric({"nA": report}, NODES, ENDPOINTS)

    (finding,) = result["findings"]
    assert finding["type"] == "vxlan-fdb-desync"
    assert finding["severity"] == "critical"
    assert finding["node"] == "alpha"
    assert finding["detail"] == {
        "mac": REMOTE_MAC,
        "ip": "10.0.1.61",
        "current_dst": None,
        "expected_dst": "100.64.0.2",
    }
    assert finding["repair"] == {
        "action": "fdb-replace",
        "label": "Repair route",
        "params": {"network": NET, "mac": REMOTE_MAC, "dst": "100.64.0.2"},
    }


def test_vtep_pointing_at_the_previous_host_is_flagged():
    report = _report(fdb=[{"mac": REMOTE_MAC, "dst": "100.64.0.3", "self": True}])
    result = analyze_fabric({"nA": report}, NODES, ENDPOINTS)

    (finding,) = result["findings"]
    assert finding["type"] == "vxlan-fdb-desync"
    assert finding["detail"]["current_dst"] == "100.64.0.3"
    assert finding["repair"]["params"]["dst"] == "100.64.0.2"


def test_bridge_entry_without_a_self_entry_is_a_desync():
    """The real shape of the bug: br0 learned the MAC, the vxlan entry is gone."""
    report = _report(fdb=[{"mac": REMOTE_MAC, "dst": None, "self": False}])
    result = analyze_fabric({"nA": report}, NODES, ENDPOINTS)
    assert _types(result) == ["vxlan-fdb-desync"]


def test_locally_hosted_endpoints_are_not_expected_in_the_fdb():
    """Traffic to a container on this node never crosses the vxlan."""
    local = [{"node_id": "nA", "network_id": NET, "ip": "10.0.1.61", "network": "app"}]
    report = _report(fdb=[{"mac": REMOTE_MAC, "dst": None, "self": True}])
    assert analyze_fabric({"nA": report}, NODES, local)["findings"] == []


def test_unknown_macs_are_ignored_as_stale_leftovers():
    report = _report(fdb=[{"mac": "02:42:0a:00:01:99", "dst": None, "self": True}])
    assert analyze_fabric({"nA": report}, NODES, ENDPOINTS)["findings"] == []


def test_overlay_mtu_exceeding_the_underlay_is_flagged():
    """Docker's 1450 default over a 1280 tunnel: small packets pass, large die."""
    report = _report(links=[{"name": "vxlan0", "mtu": 1450, "kind": "vxlan"}])
    result = analyze_fabric({"nA": report}, NODES, ENDPOINTS)

    (finding,) = result["findings"]
    assert finding["type"] == "overlay-mtu-oversize"
    assert finding["detail"]["encapsulated"] == 1500
    assert finding["detail"]["underlay_mtu"] == 1280
    assert finding["detail"]["recommended_mtu"] == 1230
    # Fixing it means recreating the network — never offered as a button.
    assert finding["repair"] is None


def test_mtu_exactly_filling_the_underlay_is_accepted():
    report = _report(links=[{"name": "vxlan0", "mtu": 1230, "kind": "vxlan"}])
    assert analyze_fabric({"nA": report}, NODES, ENDPOINTS)["findings"] == []


def test_underlay_is_chosen_by_address_not_by_lowest_mtu():
    """A physical NIC alongside the tunnel must not be mistaken for the transport."""
    root_links = [
        {"name": "end0", "mtu": 1500, "kind": None, "up": True, "operstate": "up",
         "master": None, "vxlan_id": None, "addrs": ["192.168.1.20"]},
        {"name": "tailscale0", "mtu": 1280, "kind": None, "up": True, "operstate": "up",
         "master": None, "vxlan_id": None, "addrs": ["100.64.0.1"]},
    ]
    # Node advertises its tailscale address, so 1450 is oversized...
    report = _report(links=[{"name": "vxlan0", "mtu": 1450, "kind": "vxlan"}], root_links=root_links)
    assert _types(analyze_fabric({"nA": report}, NODES, ENDPOINTS)) == ["overlay-mtu-oversize"]

    # ...but a node advertising the LAN address has 1500 of headroom.
    lan_nodes = [{"id": "nA", "hostname": "alpha", "addr": "192.168.1.20"}] + NODES[1:]
    assert analyze_fabric({"nA": report}, lan_nodes, ENDPOINTS)["findings"] == []


def test_node_missing_a_service_entry_its_peers_have():
    """The embedded-resolver desync: one node's service table lost a VIP."""
    fabric = {
        "nA": _report(),
        "nB": _report(),
        "nC": _report(service_table={NET: {}}),
    }
    result = analyze_fabric(fabric, NODES, ENDPOINTS)

    findings = [f for f in result["findings"] if f["type"] == "service-dns-desync"]
    assert len(findings) == 1
    assert findings[0]["node"] == "gamma"
    assert findings[0]["severity"] == "critical"
    assert findings[0]["detail"]["service"] == "socket-proxy"
    assert sorted(findings[0]["detail"]["known_by"]) == ["alpha", "beta"]
    # Only a daemon restart clears it, so no button is offered.
    assert findings[0]["repair"] is None


def test_a_lone_node_is_never_declared_wrong_about_the_service_table():
    """With one witness there is no majority to disagree with."""
    fabric = {"nA": _report(), "nB": _report(service_table={NET: {}})}
    result = analyze_fabric(fabric, NODES, ENDPOINTS)
    assert [f for f in result["findings"] if f["type"] == "service-dns-desync"] == []


def test_disagreeing_vips_are_flagged():
    fabric = {
        "nA": _report(),
        "nB": _report(service_table={NET: {"socket-proxy": {"vip": "10.0.2.99", "tasks": []}}}),
    }
    findings = [
        f for f in analyze_fabric(fabric, NODES, ENDPOINTS)["findings"]
        if f["type"] == "service-dns-desync"
    ]
    assert len(findings) == 1
    assert findings[0]["severity"] == "warning"
    assert findings[0]["detail"]["vips"] == {"alpha": "10.0.2.11", "beta": "10.0.2.99"}


def test_engine_up_but_swarm_module_dead():
    """The boot race: dockerd runs, the manager never bound its address."""
    report = _report(
        swarm={
            "local_state": "error",
            "error": "manager stopped: failed to listen on remote API address",
        }
    )
    result = analyze_fabric({"nA": report}, NODES, ENDPOINTS)

    (finding,) = [f for f in result["findings"] if f["type"] == "swarm-engine-degraded"]
    assert finding["severity"] == "critical"
    assert "failed to listen" in finding["detail"]["engine_error"]
    assert finding["repair"] is None


def test_orphaned_vxlan_interface_is_flagged_and_deletable():
    root_links = [
        {"name": "tailscale0", "mtu": 1280, "kind": None, "up": True, "operstate": "up",
         "master": None, "vxlan_id": None, "addrs": ["100.64.0.1"]},
        {"name": "vx-001010-xgnut", "mtu": 1450, "kind": "vxlan", "up": False,
         "operstate": "down", "master": None, "vxlan_id": 4097, "addrs": []},
    ]
    result = analyze_fabric({"nA": _report(root_links=root_links)}, NODES, ENDPOINTS)

    (finding,) = [f for f in result["findings"] if f["type"] == "stale-vxlan-iface"]
    assert finding["repair"] == {
        "action": "delete-stale-vxlan",
        "label": "Delete interface",
        "params": {"interface": "vx-001010-xgnut"},
    }
    # The VNI belongs to a live network, which the message calls out.
    assert "still in use by a live network" in finding["message"]


def test_live_vxlan_interfaces_are_left_alone():
    root_links = [
        {"name": "tailscale0", "mtu": 1280, "kind": None, "up": True, "operstate": "up",
         "master": None, "vxlan_id": None, "addrs": ["100.64.0.1"]},
        {"name": "vx-001010-xgnut", "mtu": 1450, "kind": "vxlan", "up": True,
         "operstate": "up", "master": 7, "vxlan_id": 4097, "addrs": []},
    ]
    result = analyze_fabric({"nA": _report(root_links=root_links)}, NODES, ENDPOINTS)
    assert [f for f in result["findings"] if f["type"] == "stale-vxlan-iface"] == []


def test_dns_egress_failure_is_reported_with_the_resolvers_that_failed():
    report = _report(
        dns={"ok": False, "host": "one.one.one.one", "error": "timed out after 5s",
             "resolvers": ["1.1.1.1", "100.100.100.100"]}
    )
    (finding,) = [
        f for f in analyze_fabric({"nA": report}, NODES, ENDPOINTS)["findings"]
        if f["type"] == "dns-egress-blackhole"
    ]
    assert finding["detail"]["resolvers"] == ["1.1.1.1", "100.100.100.100"]


def test_skipped_dns_probe_is_not_a_failure():
    result = analyze_fabric({"nA": _report(dns={"skipped": True, "resolvers": []})}, NODES, ENDPOINTS)
    assert result["healthy"] is True


def test_unavailable_probes_are_surfaced_rather_than_read_as_health():
    """A capability-stripped daemon must not look like a clean bill of health."""
    report = _report()
    report["netns"] = {"error": "/host/docker-netns not mounted (privileged probes disabled)"}
    report["root"] = {"error": "/host/proc/1/ns/net unavailable (host procfs not mounted)"}
    result = analyze_fabric({"nA": report}, NODES, ENDPOINTS)

    assert result["findings"] == []  # nothing was actually checked
    (probe,) = result["probes"]
    assert probe["namespaces"].startswith("unavailable:")
    assert probe["root_namespace"].startswith("unavailable:")


def test_unreachable_daemon_is_recorded_as_a_probe_gap():
    result = analyze_fabric({"nA": {"_error": "unreachable"}}, NODES, ENDPOINTS)
    (probe,) = result["probes"]
    assert probe == {"node": "alpha", "node_id": "nA", "reachable": False, "error": "unreachable"}


def test_findings_are_ranked_worst_first():
    report = _report(
        fdb=[{"mac": REMOTE_MAC, "dst": None, "self": True}],
        root_links=[
            {"name": "tailscale0", "mtu": 1280, "kind": None, "up": True, "operstate": "up",
             "master": None, "vxlan_id": None, "addrs": ["100.64.0.1"]},
            {"name": "vx-dead", "mtu": 1450, "kind": "vxlan", "up": False, "operstate": "down",
             "master": None, "vxlan_id": 9999, "addrs": []},
        ],
    )
    severities = [f["severity"] for f in analyze_fabric({"nA": report}, NODES, ENDPOINTS)["findings"]]
    assert severities == ["critical", "warning"]
