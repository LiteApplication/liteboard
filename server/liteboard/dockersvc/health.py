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

    running = [
        t
        for t in tasks
        if t.get("DesiredState") == _RUNNING
        and (t.get("Status") or {}).get("State") == _RUNNING
    ]
    desired = _desired_count(service)
    running_count = len(running)

    # Recent failures for crash-loop detection.
    recent_failures = []
    last_error = None
    last_exit_code = None
    for t in tasks:
        status = t.get("Status") or {}
        state = status.get("State")
        if state in _FAILED_STATES:
            ts = _parse_ts(status.get("Timestamp"))
            if ts and (now - ts).total_seconds() <= CRASH_WINDOW_S:
                recent_failures.append(t)
            if last_error is None and status.get("Err"):
                last_error = status.get("Err")
            cs = status.get("ContainerStatus") or {}
            if last_exit_code is None and cs.get("ExitCode") is not None:
                last_exit_code = cs.get("ExitCode")

    crash_looping = len(recent_failures) >= CRASH_FAIL_THRESHOLD

    # A rollout is in flight when Docker reports one, or when the server itself
    # just triggered a redeploy/update (tracked in-memory for a grace window).
    docker_updating = (service.get("update_status") or {}).get("State") in {
        "updating",
        "paused",
    }
    updating = docker_updating or redeploying

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
        "recent_failures": len(recent_failures),
        "last_error": last_error,
        "last_exit_code": last_exit_code,
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
