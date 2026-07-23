"""Image disk-usage counting + background prune job on the daemon.

Counting must stay off ``/system/df`` (expensive, drives dockerd CPU/IO hard)
and use the cheap ``/images/json`` + ``/containers/json`` combo instead.
Pruning deletes images one at a time so progress can be polled instead of
blocking until Docker's bulk prune finishes.
"""

import importlib
import sys
import time
from pathlib import Path

DAEMON_DIR = Path(__file__).resolve().parents[2] / "daemon"


def _load_images(monkeypatch):
    monkeypatch.syspath_prepend(str(DAEMON_DIR))
    for mod in ("images", "dockerapi"):
        sys.modules.pop(mod, None)
    return importlib.import_module("images")


def test_disk_usage_never_calls_system_df(monkeypatch):
    images = _load_images(monkeypatch)

    calls = []

    def fake_get(path, socket_path, timeout=5.0):
        calls.append(path)
        if path == "/images/json":
            return [
                {"Id": "sha256:a", "Size": 100},
                {"Id": "sha256:b", "Size": 50},
            ]
        if path == "/containers/json?all=true":
            return [{"ImageID": "sha256:a"}]
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(images.dockerapi, "get", fake_get)

    result = images.disk_usage("/var/run/docker.sock")

    assert "/system/df" not in calls
    assert result == {
        "image_count": 2,
        "total_size": 150,
        "unused_count": 1,
        "unused_size": 50,
    }


def test_disk_usage_reports_error_without_crashing(monkeypatch):
    images = _load_images(monkeypatch)

    def fake_get(path, socket_path, timeout=5.0):
        raise RuntimeError("docker api GET /images/json -> 500")

    monkeypatch.setattr(images.dockerapi, "get", fake_get)

    result = images.disk_usage("/var/run/docker.sock")
    assert "error" in result


def test_prune_job_deletes_unused_images_and_reports_progress(monkeypatch):
    images = _load_images(monkeypatch)

    def fake_get(path, socket_path, timeout=5.0):
        if path == "/images/json":
            return [
                {"Id": "sha256:a", "Size": 100},
                {"Id": "sha256:b", "Size": 50},
            ]
        if path == "/containers/json?all=true":
            return []  # nothing in use -> both images are prune candidates
        raise AssertionError(f"unexpected path {path}")

    deleted = []

    def fake_delete(path, socket_path, timeout=5.0):
        deleted.append(path)
        return [{"Deleted": path}]

    monkeypatch.setattr(images.dockerapi, "get", fake_get)
    monkeypatch.setattr(images.dockerapi, "delete", fake_delete)

    job_id = images.start_prune("/var/run/docker.sock")

    deadline = time.time() + 2
    status = images.job_status(job_id)
    while status["status"] == "running" and time.time() < deadline:
        time.sleep(0.01)
        status = images.job_status(job_id)

    assert status["status"] == "done"
    assert status["total"] == 2
    assert status["done"] == 2
    assert status["deleted"] == 2
    assert status["space_reclaimed"] == 150
    assert len(deleted) == 2


def test_job_status_unknown_job_reports_error(monkeypatch):
    images = _load_images(monkeypatch)
    assert images.job_status("does-not-exist") == {"error": "job not found"}
