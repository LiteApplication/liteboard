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
