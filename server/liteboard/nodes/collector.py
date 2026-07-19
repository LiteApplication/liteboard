"""Fan-out signed queries to every node's daemon and cache the latest snapshot.

Runs a background poll loop (interval from settings). Each request is signed with
the server's private key so only this server can talk to the daemons. Results are
kept in memory only (live-only metrics — no persistence).
"""

from __future__ import annotations

import asyncio
import time

import httpx

from ..config import Settings, get_settings
from ..crypto.signer import Signer
from ..dockersvc import swarm


class NodeCollector:
    def __init__(self, signer: Signer, settings: Settings | None = None) -> None:
        self._signer = signer
        self._settings = settings or get_settings()
        self._metrics: dict[str, dict] = {}
        self._networks: dict[str, dict] = {}
        self._nodes: list[dict] = []
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    # -- lifecycle --------------------------------------------------------- #
    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.poll_once()
            except Exception:  # noqa: BLE001 - keep the loop alive
                pass
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self._settings.poll_interval
                )
            except asyncio.TimeoutError:
                pass

    # -- daemon addressing ------------------------------------------------- #
    def _daemon_url(self, node: dict, path: str) -> str | None:
        addr = (node.get("addr") or "").split(":")[0]
        if not addr:
            return None
        s = self._settings
        return f"{s.daemon_scheme}://{addr}:{s.daemon_port}{path}"

    async def _fetch(
        self, client: httpx.AsyncClient, node: dict, path: str
    ) -> dict | None:
        url = self._daemon_url(node, path)
        if not url:
            return None
        # Sign over the path only (host-independent), matching the daemon.
        headers = self._signer.sign_headers("GET", path)
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            return {"_error": f"HTTP {resp.status_code}", "_detail": resp.text[:200]}
        except httpx.HTTPError as exc:
            return {"_error": "unreachable", "_detail": str(exc)}

    # -- polling ----------------------------------------------------------- #
    async def poll_once(self) -> None:
        nodes = await asyncio.to_thread(swarm.list_nodes)
        s = self._settings
        async with httpx.AsyncClient(timeout=s.daemon_timeout) as client:
            metric_results = await asyncio.gather(
                *(self._fetch(client, n, "/metrics") for n in nodes)
            )
            version_results = await asyncio.gather(
                *(self._fetch(client, n, "/version") for n in nodes)
            )
            network_results = await asyncio.gather(
                *(self._fetch(client, n, "/networks") for n in nodes)
            )

        async with self._lock:
            self._nodes = nodes
            for node, metrics, version, networks in zip(
                nodes, metric_results, version_results, network_results
            ):
                nid = node["id"]
                reachable = bool(metrics) and "_error" not in metrics
                self._metrics[nid] = {
                    "reachable": reachable,
                    "error": (metrics or {}).get("_error"),
                    "metrics": metrics if reachable else None,
                    "daemon": version if version and "_error" not in version else None,
                    "polled_at": time.time(),
                }
                if networks and "_error" not in networks:
                    self._networks[nid] = networks

    # -- accessors --------------------------------------------------------- #
    async def snapshot(self) -> list[dict]:
        async with self._lock:
            out = []
            for node in self._nodes:
                nid = node["id"]
                entry = self._metrics.get(nid, {})
                out.append({"node": node, **entry})
            return out

    async def networks_by_node(self) -> dict[str, dict]:
        async with self._lock:
            return {
                nid: self._networks.get(nid, {})
                for nid in (n["id"] for n in self._nodes)
            }

    async def nodes(self) -> list[dict]:
        async with self._lock:
            return list(self._nodes)

    async def push_update(self, bundle: dict) -> list[dict]:
        """POST a signed self-update bundle to every reachable daemon."""
        import json

        nodes = await self.nodes()
        body = json.dumps(bundle).encode()
        headers = self._signer.sign_headers("POST", "/update", body)
        headers["Content-Type"] = "application/json"
        results = []
        async with httpx.AsyncClient(timeout=self._settings.daemon_timeout) as client:
            for node in nodes:
                url = self._daemon_url(node, "/update")
                if not url:
                    continue
                try:
                    resp = await client.post(url, content=body, headers=headers)
                    results.append(
                        {"node": node["hostname"], "status": resp.status_code, "body": resp.json()}
                    )
                except httpx.HTTPError as exc:
                    results.append({"node": node["hostname"], "error": str(exc)})
        return results
