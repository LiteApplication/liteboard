"""Shared application state: the request signer and the node collector."""

from __future__ import annotations

from .config import Settings, get_settings
from .crypto.signer import Signer
from .nodes.collector import NodeCollector


class AppState:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.signer = Signer(self.settings.load_signing_key())
        self.collector = NodeCollector(self.signer, self.settings)

    def start(self) -> None:
        self.collector.start()

    async def stop(self) -> None:
        await self.collector.stop()


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
