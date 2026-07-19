"""Tests for cross-node network consistency analysis."""

from liteboard.nodes.networks import analyze_networks


def _view(networks):
    return {"networks": networks}


def test_consistent_when_replicas_have_distinct_ips():
    by_node = {
        "n1": _view([
            {"name": "app_net", "subnet": "10.0.1.0/24", "endpoints": [
                {"name": "web.1.aaa", "service": "app_web", "ipv4": "10.0.1.2"},
            ]},
        ]),
        "n2": _view([
            {"name": "app_net", "subnet": "10.0.1.0/24", "endpoints": [
                {"name": "web.2.bbb", "service": "app_web", "ipv4": "10.0.1.3"},
            ]},
        ]),
    }
    result = analyze_networks(by_node)
    assert result["consistent"] is True
    assert result["warnings"] == []


def test_ip_collision_flagged():
    by_node = {
        "n1": _view([
            {"name": "app_net", "endpoints": [
                {"name": "web.1.aaa", "service": "app_web", "ipv4": "10.0.1.9"},
                {"name": "db.1.ccc", "service": "app_db", "ipv4": "10.0.1.9"},
            ]},
        ]),
    }
    result = analyze_networks(by_node)
    types = {w["type"] for w in result["warnings"]}
    assert "ip-collision" in types
    assert result["consistent"] is False


def test_subnet_mismatch_flagged():
    by_node = {
        "n1": _view([{"name": "app_net", "subnet": "10.0.1.0/24", "endpoints": [
            {"name": "web.1.a", "service": "web", "ipv4": "10.0.1.2"}]}]),
        "n2": _view([{"name": "app_net", "subnet": "10.0.2.0/24", "endpoints": [
            {"name": "web.2.b", "service": "web", "ipv4": "10.0.2.2"}]}]),
    }
    result = analyze_networks(by_node)
    assert any(w["type"] == "subnet-mismatch" for w in result["warnings"])


def test_same_task_different_ip_flagged():
    by_node = {
        "n1": _view([{"name": "app_net", "endpoints": [
            {"name": "web.1.aaa", "service": "web", "ipv4": "10.0.1.2"}]}]),
        "n2": _view([{"name": "app_net", "endpoints": [
            {"name": "web.1.aaa", "service": "web", "ipv4": "10.0.1.5"}]}]),
    }
    result = analyze_networks(by_node)
    conflicts = [w for w in result["warnings"] if w["type"] == "task-ip-conflict"]
    assert conflicts and conflicts[0]["task"] == "web.1"
