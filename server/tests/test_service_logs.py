"""service_logs: line parsing, session scoping, and the since-cursor poll path."""

import pytest

from liteboard.dockersvc import swarm
from liteboard.dockersvc.health import _parse_ts


def test_parse_log_lines_splits_timestamp_and_text():
    raw = (
        "2026-07-19T16:35:10.756543443Z hello\n"
        "2026-07-19T16:35:10.756547731Z world\n"
    )
    assert swarm._parse_log_lines(raw) == [
        {"ts": "2026-07-19T16:35:10.756543443Z", "text": "hello"},
        {"ts": "2026-07-19T16:35:10.756547731Z", "text": "world"},
    ]


def test_parse_log_lines_keeps_malformed_line_verbatim():
    assert swarm._parse_log_lines("not-a-timestamp line") == [
        {"ts": None, "text": "not-a-timestamp line"}
    ]


def test_parse_log_lines_empty():
    assert swarm._parse_log_lines("") == []


class FakeTask:
    def __init__(self, created_at):
        self._created_at = created_at

    def get(self, key, default=None):
        return {"CreatedAt": self._created_at}.get(key, default)


class FakeService:
    def __init__(self, name="web", tasks=None, log_text=""):
        self.attrs = {"Spec": {"Name": name}}
        self._tasks = tasks or []
        self._log_text = log_text
        self.logs_calls = []

    def tasks(self):
        return self._tasks

    def logs(self, **kwargs):
        self.logs_calls.append(kwargs)
        return self._log_text.encode()


class FakeServices:
    def __init__(self, svc):
        self._svc = svc

    def get(self, service_id):
        return self._svc


class FakeClient:
    def __init__(self, svc):
        self.services = FakeServices(svc)


@pytest.fixture
def patch_client(monkeypatch):
    def _install(svc):
        monkeypatch.setattr(swarm, "get_client", lambda: FakeClient(svc))
        return svc

    return _install


def test_initial_load_scopes_since_to_task_start(patch_client):
    svc = FakeService(
        tasks=[{"CreatedAt": "2026-07-19T16:00:00.000000000Z"}],
        log_text="2026-07-19T16:35:10.756543443Z hello\n",
    )
    patch_client(svc)
    result = swarm.service_logs("s1", tail=300)

    assert result["logs"] == [{"ts": "2026-07-19T16:35:10.756543443Z", "text": "hello"}]
    assert result["since"] == "2026-07-19T16:00:00+00:00"
    call = svc.logs_calls[0]
    assert call["tail"] == 300
    assert call["since"] == int(_parse_ts("2026-07-19T16:00:00.000000000Z").timestamp()) - 2


def test_since_ts_overrides_session_scoping_for_polling(patch_client):
    svc = FakeService(log_text="2026-07-19T16:36:00.000000000Z new line\n")
    patch_client(svc)
    result = swarm.service_logs("s1", tail=300, since_ts=1700000000.5)

    assert result["since"] is None  # no session lookup done on the poll path
    assert svc.logs_calls[0]["since"] == 1700000000
    assert svc.tasks() == []  # tasks() not consulted when since_ts is given


def test_has_more_true_only_when_full_page_and_not_polling(patch_client):
    svc = FakeService(tasks=[], log_text="".join(f"2026-07-19T16:00:0{i}.000000000Z l{i}\n" for i in range(3)))
    patch_client(svc)

    assert swarm.service_logs("s1", tail=3)["has_more"] is True
    assert swarm.service_logs("s1", tail=10)["has_more"] is False
    assert swarm.service_logs("s1", tail=3, since_ts=1.0)["has_more"] is False


def test_tail_clamped_to_max(patch_client):
    svc = FakeService()
    patch_client(svc)
    swarm.service_logs("s1", tail=999999)
    assert svc.logs_calls[0]["tail"] == swarm.MAX_LOG_TAIL
