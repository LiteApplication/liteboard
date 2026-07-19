"""The daemon boots 'unprovisioned' (no crash) when it has no server pubkey."""

import importlib
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from liteboard.crypto import protocol

DAEMON_DIR = Path(__file__).resolve().parents[2] / "daemon"


def _load_daemon(monkeypatch, pubkey):
    monkeypatch.setenv("LITEBOARD_SERVER_PUBKEY", pubkey)
    monkeypatch.syspath_prepend(str(DAEMON_DIR))
    for mod in ("liteboard_daemon",):
        sys.modules.pop(mod, None)
    return importlib.import_module("liteboard_daemon")


def test_boots_unprovisioned_without_key(monkeypatch):
    mod = _load_daemon(monkeypatch, "")
    try:
        assert mod.DAEMON.provisioned is False
        assert mod.DAEMON.pubkey is None
    finally:
        mod.DAEMON.metrics.stop()


def test_boots_provisioned_with_key(monkeypatch):
    pub = protocol.public_key_b64(Ed25519PrivateKey.generate())
    mod = _load_daemon(monkeypatch, pub)
    try:
        assert mod.DAEMON.provisioned is True
        assert mod.DAEMON.pubkey is not None
    finally:
        mod.DAEMON.metrics.stop()
