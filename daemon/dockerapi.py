"""Tiny raw HTTP-over-unix-socket client for the local Docker API.

Used instead of docker-py so the daemon stays dependency-light (``psutil`` +
``cryptography`` only). Shared by ``netinspect.py`` and ``images.py``.
"""

from __future__ import annotations

import http.client
import json
import socket


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float = 5.0) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:  # noqa: D401
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._socket_path)
        self.sock = sock


def request(
    method: str,
    path: str,
    socket_path: str,
    body: bytes | None = None,
    timeout: float = 5.0,
) -> object:
    conn = UnixHTTPConnection(socket_path, timeout=timeout)
    try:
        headers = {"Host": "docker"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        if resp.status >= 400:
            raise RuntimeError(f"docker api {method} {path} -> {resp.status}: {data[:200]!r}")
        return json.loads(data) if data else {}
    finally:
        conn.close()


def get(path: str, socket_path: str, timeout: float = 5.0) -> object:
    return request("GET", path, socket_path, timeout=timeout)


def post(path: str, socket_path: str, body: bytes | None = None, timeout: float = 5.0) -> object:
    return request("POST", path, socket_path, body=body, timeout=timeout)


def delete(path: str, socket_path: str, timeout: float = 5.0) -> object:
    return request("DELETE", path, socket_path, timeout=timeout)
