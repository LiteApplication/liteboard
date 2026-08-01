"""Tests for the Swarm health classifier."""

from datetime import datetime, timedelta, timezone

from liteboard.dockersvc import health


def _now():
    return datetime.now(timezone.utc)


def _ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000000000Z")


def _running_task(node="n1"):
    return {"DesiredState": "running", "NodeID": node, "Status": {"State": "running"}}


def _failed_task(secs_ago=10, err="boom", exit_code=1):
    ts = _ts(_now() - timedelta(seconds=secs_ago))
    return {
        "DesiredState": "shutdown",
        "NodeID": "n1",
        "Status": {
            "State": "failed",
            "Timestamp": ts,
            "Err": err,
            "ContainerStatus": {"ExitCode": exit_code},
        },
    }


def _service(name, replicas=1, tasks=None, image="nginx:latest@sha256:abc"):
    return {
        "id": f"id-{name}",
        "name": name,
        "image": image,
        "labels": {},
        "mode": {"Replicated": {"Replicas": replicas}},
        "update_status": None,
        "tasks": tasks or [],
    }


def test_healthy_service():
    svc = _service("web", replicas=2, tasks=[_running_task(), _running_task("n2")])
    result = health.classify_service(svc)
    assert result["state"] == "healthy"
    assert result["running"] == 2
    assert result["running_node_ids"] == ["n1", "n2"]
    assert result["desired"] == 2


def test_under_replicated_is_degraded():
    svc = _service("web", replicas=3, tasks=[_running_task()])
    result = health.classify_service(svc)
    assert result["state"] == "degraded"
    assert result["running"] == 1
    assert result["desired"] == 3


def test_zero_of_one_is_down():
    svc = _service("db", replicas=1, tasks=[])
    result = health.classify_service(svc)
    assert result["state"] == "down"
    assert result["running"] == 0


def test_crash_loop_detected():
    tasks = [_failed_task(secs_ago=s) for s in (5, 20, 40)]
    svc = _service("crasher", replicas=1, tasks=tasks)
    result = health.classify_service(svc)
    assert result["state"] == "crash-loop"
    assert result["crash_looping"] is True
    assert result["last_error"] == "boom"
    assert result["last_exit_code"] == 1


def test_old_failures_not_crash_loop():
    # Failures well outside the crash window shouldn't count.
    tasks = [_failed_task(secs_ago=5000) for _ in range(5)] + [_running_task()]
    svc = _service("stable", replicas=1, tasks=tasks)
    result = health.classify_service(svc)
    assert result["state"] == "healthy"
    assert result["last_error"] is None
    assert result["last_exit_code"] is None


def test_healthy_service_clears_error():
    # Even if there was a recent failure, if the service is healthy (all replicas running),
    # last_error and last_exit_code should be cleared to avoid showing stale warnings.
    tasks = [_failed_task(secs_ago=10), _running_task()]
    svc = _service("stable", replicas=1, tasks=tasks)
    result = health.classify_service(svc)
    assert result["state"] == "healthy"
    assert result["last_error"] is None
    assert result["last_exit_code"] is None


def test_global_mode_desired_from_nodes():
    svc = {
        "id": "g", "name": "agent", "image": "x:1@sha256:a", "labels": {},
        "mode": {"Global": {}}, "update_status": None,
        "tasks": [
            {"DesiredState": "running", "NodeID": "n1", "Status": {"State": "running"}},
            {"DesiredState": "running", "NodeID": "n2", "Status": {"State": "running"}},
        ],
    }
    result = health.classify_service(svc)
    assert result["mode"] == "global"
    assert result["desired"] == 2
    assert result["state"] == "healthy"


def test_docker_update_beats_down():
    # Tasks momentarily gone during a rollout: show "updating", not "down".
    svc = _service("web", replicas=1, tasks=[])
    svc["update_status"] = {"State": "updating"}
    assert health.classify_service(svc)["state"] == "updating"


def test_stale_docker_update_on_converged_service_is_healthy():
    # Docker leaves UpdateStatus at "updating" forever when a rollout is
    # interrupted; a fully-running service must not read as "Updating".
    running = _running_task()
    running["Slot"] = 1
    running["Status"]["Timestamp"] = _ts(_now() - timedelta(hours=29))
    svc = _service("jellyseerr", replicas=1, tasks=[running])
    svc["update_status"] = {"State": "updating"}
    assert health.classify_service(svc)["state"] == "healthy"


def test_paused_rollout_is_surfaced_as_advisory():
    running = _running_task()
    running["Slot"] = 1
    running["Status"]["Timestamp"] = _ts(_now() - timedelta(hours=29))
    svc = _service("jellyseerr", replicas=1, tasks=[running])
    svc["update_status"] = {
        "State": "paused",
        "StartedAt": _ts(_now() - timedelta(days=2)),
        "Message": "update paused due to failure or early termination of task abc",
    }
    r = health.classify_service(svc)
    assert r["state"] == "healthy"
    assert r["rollout"]["state"] == "paused"
    assert "early termination" in r["rollout"]["message"]


def test_in_flight_rollout_has_no_paused_advisory():
    svc = _service("web", replicas=1, tasks=[])
    svc["update_status"] = {"State": "paused", "StartedAt": _ts(_now())}
    r = health.classify_service(svc)
    assert r["state"] == "updating"
    assert r["rollout"] is None


def test_stale_docker_update_ignored_even_when_down():
    svc = _service("web", replicas=1, tasks=[])
    svc["update_status"] = {
        "State": "updating",
        "StartedAt": _ts(_now() - timedelta(seconds=health.UPDATE_STALE_S + 60)),
    }
    assert health.classify_service(svc)["state"] == "down"


def test_in_flight_rollout_still_updating_while_old_task_runs():
    # New task starting while the old replica still runs: converged by count,
    # but there is something in flight -> "updating".
    old = _running_task()
    old["Slot"] = 1
    new = {"DesiredState": "running", "Slot": 1, "NodeID": "n1",
           "Status": {"State": "preparing", "Timestamp": _ts(_now())}}
    svc = _service("web", replicas=1, tasks=[old, new])
    svc["update_status"] = {"State": "updating", "StartedAt": _ts(_now())}
    assert health.classify_service(svc)["state"] == "updating"


def test_failure_before_current_running_task_is_not_reported():
    # Slot rejected twice, then started fine 29h ago -> no stale warning.
    rejected = _failed_task(secs_ago=30 * 3600, err="No such image", exit_code=0)
    rejected["Slot"] = 1
    rejected["Status"]["State"] = "rejected"
    running = _running_task()
    running["Slot"] = 1
    running["Status"]["Timestamp"] = _ts(_now() - timedelta(hours=29))
    svc = _service("immich", replicas=1, tasks=[running, rejected])
    result = health.classify_service(svc)
    assert result["state"] == "healthy"
    assert result["last_error"] is None


def test_failure_on_a_slot_with_nothing_running_is_reported():
    failed = _failed_task(secs_ago=60, err="boom")
    failed["Slot"] = 2
    running = _running_task()
    running["Slot"] = 1
    running["Status"]["Timestamp"] = _ts(_now() - timedelta(hours=5))
    svc = _service("web", replicas=2, tasks=[running, failed])
    result = health.classify_service(svc)
    assert result["state"] == "degraded"
    assert result["last_error"] == "boom"


def test_zero_exit_code_is_not_reported():
    failed = _failed_task(secs_ago=60, err="failed to lookup digest", exit_code=0)
    svc = _service("lidarr", replicas=1, tasks=[failed])
    result = health.classify_service(svc)
    assert result["last_error"] == "failed to lookup digest"
    assert result["last_exit_code"] is None


def test_redeploying_flag_beats_down():
    svc = _service("web", replicas=1, tasks=[])
    assert health.classify_service(svc, redeploying=True)["state"] == "updating"


def test_redeploying_does_not_mask_crash_loop():
    tasks = [_failed_task(secs_ago=s) for s in (5, 20, 40)]
    svc = _service("web", replicas=1, tasks=tasks)
    assert health.classify_service(svc, redeploying=True)["state"] == "crash-loop"


def test_build_overview_honors_redeploying_ids():
    services = [_service("web", replicas=1, tasks=[])]
    ov = health.build_overview(services, {"id-web"})
    assert ov["services"][0]["state"] == "updating"
    assert ov["counts"]["updating"] == 1
    assert ov["counts"]["down"] == 0


def test_overview_ordering_and_counts():
    services = [
        _service("ok", tasks=[_running_task()]),
        _service("crash", tasks=[_failed_task(s) for s in (1, 2, 3)]),
        _service("degraded", replicas=2, tasks=[_running_task()]),
    ]
    ov = health.build_overview(services)
    assert ov["services"][0]["state"] == "crash-loop"
    assert ov["counts"]["crash-loop"] == 1
    assert ov["counts"]["degraded"] == 1
    assert ov["counts"]["healthy"] == 1


def test_transitioning_tasks_extracted():
    # If a task is desired to run but is not yet running, it should be listed in transitioning.
    tasks = [
        {"DesiredState": "running", "Slot": 1, "NodeID": "n1", "Status": {"State": "preparing", "Message": "pulling image"}},
        {"DesiredState": "running", "Slot": 2, "NodeID": "n1", "Status": {"State": "running"}},
    ]
    svc = _service("web", replicas=2, tasks=tasks)
    result = health.classify_service(svc)
    assert result["state"] == "degraded"
    assert len(result["transitioning"]) == 1
    assert result["transitioning"][0]["slot"] == 1
    assert result["transitioning"][0]["state"] == "preparing"
    assert result["transitioning"][0]["message"] == "pulling image"
