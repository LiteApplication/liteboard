"""LiteBoard API routes (all guarded by the OIDC session)."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..auth.oidc import require_user
from ..daemon_dist import bundle as daemon_bundle
from ..dockersvc import health, redeploys, swarm, updates
from ..nodes.networks import analyze_networks
from ..state import get_state

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


@router.get("/overview")
async def overview():
    services = await asyncio.to_thread(swarm.list_services_with_tasks)
    result = health.build_overview(services, redeploys.active_ids())
    result["swarm"] = await asyncio.to_thread(swarm.swarm_info)
    server_id, server_name = await asyncio.to_thread(swarm.get_server_service_info)
    result["server_service_id"] = server_id
    result["server_service_name"] = server_name
    return result


@router.get("/services/{service_id}/logs")
async def service_logs(service_id: str):
    """Logs of the service's most recent task ("last session" — start to crash)."""
    try:
        return await asyncio.to_thread(swarm.service_logs, service_id)
    except Exception as exc:  # noqa: BLE001  (docker-py NotFound etc.)
        raise HTTPException(404, f"could not fetch logs: {exc}")


@router.post("/services/{service_id}/redeploy")
async def redeploy_service(service_id: str):
    """Force a rolling restart of the service (new tasks, same image)."""
    try:
        await asyncio.to_thread(swarm.force_update_service, service_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"could not redeploy: {exc}")
    redeploys.mark(service_id)
    return {"ok": True}


@router.get("/updates")
async def list_updates():
    services = await asyncio.to_thread(swarm.list_services_with_tasks)
    return {"services": await updates.check_updates(services)}


@router.post("/updates/{service_id}/apply")
async def apply_one(service_id: str):
    services = await asyncio.to_thread(swarm.list_services_with_tasks)
    match = next((s for s in services if s["id"] == service_id), None)
    if not match:
        raise HTTPException(404, "service not found")
    checked = (await updates.check_updates([match]))[0]
    if checked["status"] not in {"outdated", "unpinned"} or not checked["remote_digest"]:
        raise HTTPException(409, f"cannot update or pin service (status: {checked['status']})")
    await asyncio.to_thread(
        updates.apply_update,
        service_id,
        checked["repository"],
        checked["tag"],
        checked["registry"],
        checked["remote_digest"],
    )
    redeploys.mark(service_id)
    return {"ok": True, "service": checked["name"], "digest": checked["remote_digest"]}


@router.post("/updates/apply-all")
async def apply_all():
    services = await asyncio.to_thread(swarm.list_services_with_tasks)
    checked = await updates.check_updates(services)
    server_id, _ = await asyncio.to_thread(swarm.get_server_service_info)
    applied = []
    for item in checked:
        if item["update_available"] and item["remote_digest"]:
            await asyncio.to_thread(
                updates.apply_update,
                item["id"],
                item["repository"],
                item["tag"],
                item["registry"],
                item["remote_digest"],
            )
            redeploys.mark(item["id"])
            applied.append({"id": item["id"], "service": item["name"], "digest": item["remote_digest"]})
    server_updated = any(a["id"] == server_id for a in applied) if server_id else False
    return {"ok": True, "applied": applied, "count": len(applied), "server_updated": server_updated}


from pydantic import BaseModel

class RegistryLoginRequest(BaseModel):
    registry: str
    username: str
    password: str

@router.post("/registry/login")
async def registry_login(req: RegistryLoginRequest):
    from ..registry.manifest import verify_credentials, RegistryAuth
    # Verify credentials
    ok = await verify_credentials(req.registry, req.username, req.password)
    if not ok:
        raise HTTPException(400, "Invalid credentials or registry unreachable")
    
    # Save the credentials
    from ..config import data_dir
    mutable_path = data_dir() / "registry_config.json"
    RegistryAuth.write_credential(str(mutable_path), req.registry, req.username, req.password)
    return {"ok": True}


@router.get("/nodes")
async def nodes():
    state = get_state()
    return {"nodes": await state.collector.snapshot()}


@router.get("/nodes/join-info")
async def nodes_join_info():
    """Swarm join tokens + daemon version, for bootstrapping a new node."""
    info = await asyncio.to_thread(swarm.join_info)
    info["daemon_version"] = daemon_bundle.daemon_version()
    return info


@router.get("/networks")
async def networks():
    state = get_state()
    by_node = await state.collector.networks_by_node()
    return analyze_networks(by_node)


@router.get("/daemons/version")
async def daemon_version():
    return {"server_bundle_version": daemon_bundle.daemon_version()}


@router.post("/daemons/push-update")
async def push_update():
    state = get_state()
    bundle = daemon_bundle.build_bundle(state.signer)
    results = await state.collector.push_update(bundle)
    return {"ok": True, "version": bundle["version"], "results": results}


@router.get("/stream")
async def stream():
    """Server-Sent Events feed with periodic overview + node snapshots."""
    state = get_state()

    async def gen():
        while True:
            try:
                services = await asyncio.to_thread(swarm.list_services_with_tasks)
                overview_data = health.build_overview(services, redeploys.active_ids())
                node_data = await state.collector.snapshot()
                payload = {"overview": overview_data, "nodes": node_data}
                yield f"event: tick\ndata: {json.dumps(payload)}\n\n"
            except Exception as exc:  # noqa: BLE001
                yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"
            await asyncio.sleep(max(state.settings.poll_interval, 2.0))

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
