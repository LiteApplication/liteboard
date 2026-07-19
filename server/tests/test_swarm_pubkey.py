"""ensure_daemon_pubkey injects the signing pubkey into the daemon service."""

import pytest

from liteboard.dockersvc import swarm


class FakeService:
    def __init__(self, env, *, name="liteboard_daemon", labelled=True, sid="s1", version=7):
        self.id = sid
        self.version = version
        self.attrs = {
            "Spec": {
                "Name": name,
                "Labels": {"liteboard.role": "daemon"} if labelled else {},
                "Mode": {"Global": {}},
                "TaskTemplate": {"ContainerSpec": {"Image": "img", "Env": list(env)}},
            }
        }


class FakeApi:
    def __init__(self):
        self.calls = []

    def update_service(self, sid, version, **kw):
        self.calls.append((sid, version, kw))


class FakeServices:
    def __init__(self, svcs):
        self._svcs = svcs

    def list(self, filters=None):
        if filters and "label" in filters:
            return [s for s in self._svcs if s.attrs["Spec"]["Labels"]]
        return list(self._svcs)


class FakeClient:
    def __init__(self, svcs):
        self.services = FakeServices(svcs)
        self.api = FakeApi()


@pytest.fixture
def patch_client(monkeypatch):
    def _install(svcs):
        client = FakeClient(svcs)
        monkeypatch.setattr(swarm, "get_client", lambda: client)
        return client

    return _install


def test_injects_pubkey_when_absent(patch_client):
    client = patch_client([FakeService(env=["FOO=bar"])])
    assert swarm.ensure_daemon_pubkey("PUB") == "updated"
    assert len(client.api.calls) == 1
    env = client.api.calls[0][2]["task_template"]["ContainerSpec"]["Env"]
    assert "LITEBOARD_SERVER_PUBKEY=PUB" in env
    assert "FOO=bar" in env  # other env preserved


def test_replaces_stale_pubkey(patch_client):
    client = patch_client([FakeService(env=["LITEBOARD_SERVER_PUBKEY=OLD"])])
    assert swarm.ensure_daemon_pubkey("NEW") == "updated"
    env = client.api.calls[0][2]["task_template"]["ContainerSpec"]["Env"]
    assert env.count("LITEBOARD_SERVER_PUBKEY=NEW") == 1
    assert "LITEBOARD_SERVER_PUBKEY=OLD" not in env


def test_noop_when_already_correct(patch_client):
    client = patch_client([FakeService(env=["LITEBOARD_SERVER_PUBKEY=PUB"])])
    assert swarm.ensure_daemon_pubkey("PUB") == "ok"
    assert client.api.calls == []


def test_not_found_when_no_daemon(patch_client):
    client = patch_client([])
    assert swarm.ensure_daemon_pubkey("PUB") == "not-found"
    assert client.api.calls == []


def test_finds_daemon_by_name_without_label(patch_client):
    client = patch_client([FakeService(env=[], labelled=False)])
    assert swarm.ensure_daemon_pubkey("PUB") == "updated"
