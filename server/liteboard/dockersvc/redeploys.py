"""In-memory tracking of recently-triggered redeploys / updates.

When the server triggers a redeploy (or applies an image update), the service's
tasks restart and briefly report zero running replicas. To avoid flapping such a
service to ``down`` in the overview, we remember it here for a short grace window
so the health classifier can render it as ``updating`` instead.

Live-only, like the rest of LiteBoard — a process restart simply forgets the
grace windows (Docker's own ``UpdateStatus`` still covers in-flight rollouts).
"""

from __future__ import annotations

import time

# How long after a server-triggered redeploy we keep showing "updating".
GRACE_S = 90.0

_recent: dict[str, float] = {}


def mark(service_id: str) -> None:
    """Remember that ``service_id`` was just redeployed/updated."""
    _recent[service_id] = time.monotonic() + GRACE_S


def active_ids() -> set[str]:
    """IDs still within their grace window (expired entries are pruned)."""
    now = time.monotonic()
    for sid in [sid for sid, exp in _recent.items() if exp <= now]:
        _recent.pop(sid, None)
    return set(_recent)
