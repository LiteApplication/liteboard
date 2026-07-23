#!/usr/bin/env python3
"""LiteBoard node daemon.

A tiny HTTP server that runs on every Swarm node and answers the LiteBoard
server's *signed* requests with live host metrics and this node's Docker network
view. Every endpoint (except unauthenticated liveness ``/health``) requires a
valid Ed25519 signature from the server's private key, plus a fresh
timestamp+nonce to defeat replay. The daemon knows only the server's public key.

Environment:
    LITEBOARD_SERVER_PUBKEY   base64url Ed25519 public key. If empty the daemon
                              boots "unprovisioned" (liveness only) until the
                              server injects the key over the manager socket.
    LITEBOARD_DAEMON_PORT     listen port (default 9opts below)
    LITEBOARD_DAEMON_BIND     bind address (default 0.0.0.0; prefer overlay IP)
    LITEBOARD_DOCKER_SOCK     docker socket path (default /var/run/docker.sock)
    LITEBOARD_NODE_NAME       optional friendly node name
    LITEBOARD_MAX_SKEW        allowed timestamp skew seconds (default 30)
"""

from __future__ import annotations

import collections
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

import images
import protocol
import selfupdate
from metrics import MetricsCollector
from netinspect import inspect_networks

VERSION = "1.1.0"

INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))
DOCKER_SOCK = os.environ.get("LITEBOARD_DOCKER_SOCK", "/var/run/docker.sock")
MAX_SKEW = int(os.environ.get("LITEBOARD_MAX_SKEW", protocol.DEFAULT_MAX_SKEW))


class ReplayCache:
    """Bounded, time-windowed nonce cache. Thread-safe."""

    def __init__(self, window: int) -> None:
        self._window = window
        self._lock = threading.Lock()
        self._seen: "collections.OrderedDict[str, float]" = collections.OrderedDict()

    def check_and_add(self, nonce: str) -> bool:
        """Return True if the nonce was already seen (a replay)."""
        now = time.time()
        with self._lock:
            # Evict expired entries.
            cutoff = now - self._window
            while self._seen and next(iter(self._seen.values())) < cutoff:
                self._seen.popitem(last=False)
            if nonce in self._seen:
                return True
            self._seen[nonce] = now
            return False


class Daemon:
    def __init__(self) -> None:
        pub_b64 = os.environ.get("LITEBOARD_SERVER_PUBKEY", "").strip()
        # Boot even without a public key: the server hands us one over the
        # manager socket shortly after the stack deploys (which restarts this
        # task with the env populated). Until then we stay "unprovisioned" —
        # liveness only, no authenticated endpoints — rather than crash-loop.
        self.provisioned = bool(pub_b64)
        self.pubkey: Ed25519PublicKey | None = (
            protocol.load_public_key(pub_b64) if pub_b64 else None
        )
        self.key_id = protocol.key_id(pub_b64) if pub_b64 else None
        self.replay = ReplayCache(window=MAX_SKEW * 2)
        self.metrics = MetricsCollector()
        self.metrics.start()

    def authenticate(self, method: str, path: str, headers: dict, body: bytes) -> None:
        protocol.verify_request(
            self.pubkey,
            method,
            path,
            headers,
            body,
            max_skew=MAX_SKEW,
            seen_nonce=self.replay.check_and_add,
        )


DAEMON = Daemon()


class Handler(BaseHTTPRequestHandler):
    server_version = f"LiteBoardDaemon/{VERSION}"
    protocol_version = "HTTP/1.1"

    # ---- helpers ---------------------------------------------------------- #
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(length) if length else b""

    def _authed(self, body: bytes) -> bool:
        if not DAEMON.provisioned:
            self._send_json(
                503, {"error": "unprovisioned", "detail": "awaiting server public key"}
            )
            return False
        try:
            DAEMON.authenticate(
                self.command, self.path, dict(self.headers.items()), body
            )
            return True
        except protocol.VerificationError as exc:
            self._send_json(401, {"error": str(exc)})
            return False

    def log_message(self, fmt: str, *args) -> None:  # quieter default logging
        pass

    # ---- routing ---------------------------------------------------------- #
    def do_GET(self) -> None:
        route = self.path.split("?", 1)[0]
        if route == "/health":
            self._send_json(
                200,
                {"status": "ok", "version": VERSION, "provisioned": DAEMON.provisioned},
            )
            return
        body = self._read_body()
        if not self._authed(body):
            return
        if route == "/version":
            self._send_json(
                200, {"version": VERSION, "key_id": DAEMON.key_id, "install_dir": INSTALL_DIR}
            )
        elif route == "/metrics":
            self._send_json(200, DAEMON.metrics.snapshot().as_dict())
        elif route == "/networks":
            self._send_json(200, inspect_networks(DOCKER_SOCK))
        elif route == "/images":
            self._send_json(200, images.disk_usage(DOCKER_SOCK))
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        route = self.path.split("?", 1)[0]
        body = self._read_body()
        if not self._authed(body):
            return
        if route == "/update":
            self._handle_update(body)
        elif route == "/images/prune":
            self._send_json(200, images.prune_unused(DOCKER_SOCK))
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_update(self, body: bytes) -> None:
        try:
            bundle = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid json"})
            return
        try:
            new_version = selfupdate.apply_bundle(DAEMON.pubkey, bundle, INSTALL_DIR)
        except protocol.VerificationError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        if new_version == VERSION:
            self._send_json(200, {"updated": False, "version": VERSION})
            return
        self._send_json(200, {"updated": True, "version": new_version, "restarting": True})
        # Flush the response, then re-exec into the new code.
        try:
            self.wfile.flush()
        except OSError:
            pass
        threading.Timer(0.5, selfupdate.restart).start()


def main() -> None:
    bind = os.environ.get("LITEBOARD_DAEMON_BIND", "0.0.0.0")
    port = int(os.environ.get("LITEBOARD_DAEMON_PORT", "9187"))
    httpd = ThreadingHTTPServer((bind, port), Handler)
    where = f"key {DAEMON.key_id}" if DAEMON.provisioned else "UNPROVISIONED (awaiting key)"
    print(f"LiteBoard daemon {VERSION} listening on {bind}:{port} ({where})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        DAEMON.metrics.stop()
        httpd.server_close()


if __name__ == "__main__":
    main()
