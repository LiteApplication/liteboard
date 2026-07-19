"""Shared application state: the request signer and the node collector.

The server may boot **unconfigured** (fresh stack, before the setup wizard has
run). In that case there is no signing key yet, so we build neither the signer
nor the collector — the app just serves the SPA + setup routes until the wizard
completes and restarts the process. Once configured, a background task
reconciles the daemon service's ``LITEBOARD_SERVER_PUBKEY`` env with our public
key (the daemons are handed the key over the manager socket — no manual step).
"""

from __future__ import annotations

import asyncio

from .config import Settings, get_settings
from .crypto.signer import Signer
from .dockersvc import swarm
from .nodes.collector import NodeCollector


class AppState:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.signer: Signer | None = None
        self.collector: NodeCollector | None = None
        self._provision_task: asyncio.Task | None = None
        self._stop = asyncio.Event()

        if self.settings.is_configured and self.settings.has_signing_key():
            self.signer = Signer(self.settings.load_signing_key())
            self.collector = NodeCollector(self.signer, self.settings)

    @property
    def configured(self) -> bool:
        return self.collector is not None

    def start(self) -> None:
        if self.collector is not None:
            self.collector.start()
        if self.signer is not None:
            self._stop.clear()
            self._provision_task = asyncio.create_task(self._provision_loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._provision_task is not None:
            await asyncio.gather(self._provision_task, return_exceptions=True)
            self._provision_task = None
        if self.collector is not None:
            await self.collector.stop()

    async def _provision_loop(self) -> None:
        """Push our signing pubkey to the daemon service until it sticks, then
        reconcile periodically (heals key rotation and re-created services)."""
        assert self.signer is not None
        pub = self.signer.public_key_b64
        delay = 5.0
        while not self._stop.is_set():
            try:
                result = await asyncio.to_thread(swarm.ensure_daemon_pubkey, pub)
            except Exception:  # noqa: BLE001 - not a manager yet / transient
                result = "error"
            # Steady state once provisioned; short backoff while unavailable.
            delay = 300.0 if result in ("ok", "updated") else min(delay * 2, 60.0)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                continue


_state: AppState | None = None


def init_state() -> AppState:
    global _state
    if _state is None:
        _state = AppState()
    return _state


def get_state() -> AppState:
    if _state is None:
        raise RuntimeError("app state not initialised")
    return _state
