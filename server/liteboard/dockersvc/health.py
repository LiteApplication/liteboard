"""Classify Swarm services into health states.

States (worst-first): ``crash-loop`` > ``down`` > ``degraded`` > ``updating`` >
``healthy``. Derived purely from the service spec + its task history so the UI
can render a prioritized "what's broken" list.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

# A task state is "live" when both its actual and desired state are running.
_RUNNING = "running"
_FAILED_STATES = {"failed", "rejected"}

# Window for counting recent failures when detecting crash loops.
CRASH_WINDOW_S = 600
CRASH_FAIL_THRESHOLD = 3

# Docker never clears ``UpdateStatus.State == "updating"`` when a rollout is
# interrupted (manager restart, a rejected task that later recovered on its own).
# Past this age we stop believing it — otherwise a long-settled service reads as
# "Updating" forever.
UPDATE_STALE_S = 3600


# RFC3339 with optional nanosecond fraction and Z/offset, e.g.
# 2024-01-01T00:00:00.123456789Z  or  2024-01-01T00:00:00+00:00
_TS_RE = re.compile(
    r"^(?P<base>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?P<tz>Z|[+-]\d{2}:?\d{2})?$"
)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    m = _TS_RE.match(value.strip())
    if not m:
        return None
    base = m.group("base")
    frac = (m.group("frac") or "")[:6].ljust(6, "0") if m.group("frac") else "000000"
    tz = m.group("tz") or "Z"
    tz = "+00:00" if tz == "Z" else tz
    if ":" not in tz[1:]:  # normalise +0000 -> +00:00
        tz = tz[:3] + ":" + tz[3:]
    try:
        return datetime.fromisoformat(f"{base}.{frac}{tz}")
    except ValueError:
        return None


def _desired_count(service: dict) -> int | None:
    mode = service.get("mode", {})
    replicated = mode.get("Replicated")
    if replicated is not None:
        return replicated.get("Replicas", 0)
    if "Global" in mode:
        # Desired = number of distinct nodes with a desired-running task.
        nodes = {
            t.get("NodeID")
            for t in service.get("tasks", [])
            if t.get("DesiredState") == _RUNNING and t.get("NodeID")
        }
        return len(nodes) or None
    return None


def classify_service(
    service: dict, now: datetime | None = None, *, redeploying: bool = False
) -> dict:
    now = now or datetime.now(timezone.utc)
    tasks = service.get("tasks", [])

    # Sort tasks descending by Timestamp so we get the most recent tasks first.
    def task_time(t: dict) -> datetime:
        status = t.get("Status") or {}
        ts = _parse_ts(status.get("Timestamp"))
        return ts or datetime.min.replace(tzinfo=timezone.utc)

    tasks = sorted(tasks, key=task_time, reverse=True)

    running = [
        t
        for t in tasks
        if t.get("DesiredState") == _RUNNING
        and (t.get("Status") or {}).get("State") == _RUNNING
    ]
    desired = _desired_count(service)
    running_count = len(running)

    # Transitioning tasks (desired to run but not yet running)
    transitioning = []
    for t in tasks:
        desired_state = t.get("DesiredState")
        status = t.get("Status") or {}
        state = status.get("State")
        if desired_state == _RUNNING and state != _RUNNING:
            transitioning.append({
                "slot": t.get("Slot"),
                "node_id": t.get("NodeID"),
                "state": state,
                "message": status.get("Message"),
                "err": status.get("Err"),
            })
    transitioning.sort(key=lambda x: (x["slot"] or 0, x["node_id"] or ""))

    # Failures that predate the currently-running generation of their own slot
    # are history: that slot already recovered from them. Slots with nothing
    # running keep all their failures (they're the ones that are actually
    # broken). Identity is the slot for replicated services, the node for
    # global ones.
    def slot_key(t: dict) -> object:
        return t.get("Slot") or t.get("NodeID")

    running_since: dict[object, datetime] = {}
    for t in running:
        key = slot_key(t)
        ts = task_time(t)
        if ts > running_since.get(key, datetime.min.replace(tzinfo=timezone.utc)):
            running_since[key] = ts

    # Recent failures for crash-loop detection.
    recent_failures = []
    last_error = None
    last_exit_code = None
    for t in tasks:
        status = t.get("Status") or {}
        state = status.get("State")
        if state not in _FAILED_STATES:
            continue
        ts = _parse_ts(status.get("Timestamp"))
        recovered_at = running_since.get(slot_key(t))
        if recovered_at is not None and (ts is None or ts <= recovered_at):
            continue
        if ts and (now - ts).total_seconds() <= CRASH_WINDOW_S:
            recent_failures.append(t)
        if last_error is None and status.get("Err"):
            last_error = status.get("Err")
            cs = status.get("ContainerStatus") or {}
            # Exit 0 on a rejected/failed task carries no signal — the failure
            # never got as far as running a container.
            if cs.get("ExitCode"):
                last_exit_code = cs.get("ExitCode")

    crash_looping = len(recent_failures) >= CRASH_FAIL_THRESHOLD
    # A single failure in the window isn't a pattern worth flagging — only
    # surface the count once there's more than one, i.e. a repeat crash.
    recent_failure_count = len(recent_failures) if len(recent_failures) > 1 else 0

    running_node_ids = sorted({t.get("NodeID") for t in running if t.get("NodeID")})

    # A rollout is in flight when Docker reports one, or when the server itself
    # just triggered a redeploy/update (tracked in-memory for a grace window).
    update_status = service.get("update_status") or {}
    docker_updating = update_status.get("State") in {"updating", "paused"}
    if docker_updating:
        # Don't trust a rollout Docker has been "running" for hours — it never
        # converged and never will (see UPDATE_STALE_S).
        started = _parse_ts(update_status.get("StartedAt"))
        if started and (now - started).total_seconds() > UPDATE_STALE_S:
            docker_updating = False
    # A converged service with nothing in flight isn't updating, whatever
    # UpdateStatus still says. `transitioning` keeps a genuine rollout (new task
    # starting while the old replica still runs) reading as "updating".
    if (
        docker_updating
        and not transitioning
        and desired is not None
        and running_count >= desired
    ):
        docker_updating = False
    updating = docker_updating or redeploying

    # A rollout Swarm has given up on. It never resolves by itself, so surface
    # it as an advisory (not a health state — the service may well be running
    # fine on whatever it settled on) with an action to clear it.
    rollout = None
    if update_status.get("State") == "paused" and not updating:
        rollout = {
            "state": "paused",
            "message": update_status.get("Message"),
            "started_at": update_status.get("StartedAt"),
        }

    # Determine state. An in-flight rollout wins over down/degraded so a service
    # whose tasks are momentarily restarting reads as "updating", not "down".
    if crash_looping:
        state = "crash-loop"
    elif updating and (desired is None or running_count < desired):
        state = "updating"
    elif desired and running_count == 0:
        state = "down"
    elif desired is not None and running_count < desired:
        state = "degraded"
    elif updating:
        state = "updating"
    else:
        state = "healthy"

    return {
        "id": service["id"],
        "name": service["name"],
        "image": service["image"],
        "mode": "global" if "Global" in service.get("mode", {}) else "replicated",
        "running": running_count,
        "desired": desired,
        "state": state,
        "crash_looping": crash_looping,
        "recent_failures": recent_failure_count,
        "last_error": last_error if state != "healthy" else None,
        "last_exit_code": last_exit_code if state != "healthy" else None,
        "transitioning": transitioning,
        "rollout": rollout,
        "running_node_ids": running_node_ids,
        "labels": service.get("labels", {}),
    }


# Ordering for the prioritized UI list.
_SEVERITY = {"crash-loop": 0, "down": 1, "degraded": 2, "updating": 3, "healthy": 4}


def build_overview(
    services: list[dict], redeploying_ids: set[str] | None = None
) -> dict:
    redeploying_ids = redeploying_ids or set()
    classified = [
        classify_service(s, redeploying=s["id"] in redeploying_ids) for s in services
    ]
    classified.sort(key=lambda s: (_SEVERITY.get(s["state"], 9), s["name"]))

    counts = {"total": len(classified)}
    for state in ("healthy", "degraded", "down", "crash-loop", "updating"):
        counts[state] = sum(1 for s in classified if s["state"] == state)

    return {
        "counts": counts,
        "services": classified,
    }
