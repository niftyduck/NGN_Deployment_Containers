import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import kathara_ctl
import placement
import ryu_client
import state

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("orchestrator")

app = FastAPI(title="NGN Orchestrator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# WebSocket log broadcast
# ---------------------------------------------------------------------------

_ws_clients: list[WebSocket] = []
_log_buffer: list[str] = []
_LOG_BUFFER_MAX = 200


class _WSLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord):
        msg = self.format(record)
        _log_buffer.append(msg)
        if len(_log_buffer) > _LOG_BUFFER_MAX:
            _log_buffer.pop(0)
        for ws in list(_ws_clients):
            try:
                asyncio.get_event_loop().call_soon_threadsafe(
                    asyncio.ensure_future, ws.send_text(msg)
                )
            except Exception:
                pass


logging.getLogger("orchestrator").addHandler(_WSLogHandler())

# ---------------------------------------------------------------------------
# Topology constants
# ---------------------------------------------------------------------------

# score ports: port 1 → s1, port 2 → s2, port 3 → s3
SWITCH_TO_SCORE_PORT: dict[str, int] = {"s1": 1, "s2": 2, "s3": 3}
UPLINK_PORT = 1   # port 1 on every edge switch = uplink to score
FLOW_PRIORITY = 100

# ethertype constants
ETH_IP = 2048   # 0x0800
ETH_ARP = 2054  # 0x0806

_TOPOLOGY_LINKS = [
    ("score", "s1"), ("score", "s2"), ("score", "s3"),
    ("s1", "h1"), ("s1", "h2"),
    ("s2", "h3"), ("s2", "h4"),
    ("s3", "h5"), ("s3", "h6"),
]

# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def on_startup():
    state.load()
    logger.info("State loaded. Discovering switch dpids…")
    try:
        await asyncio.to_thread(_discover_dpids_sync)
        logger.info("dpids: %s", state.dpids)
    except Exception as exc:
        logger.warning("dpid discovery failed (lab may not be running): %s", exc)


def _discover_dpids_sync():
    for sw in ["score", "s1", "s2", "s3"]:
        state.dpids[sw] = kathara_ctl.get_dpid(sw)
    state.save()


# ---------------------------------------------------------------------------
# Flow computation helpers
# ---------------------------------------------------------------------------

def _fwd(dpid: int, match: dict, out_port: int) -> tuple:
    return (dpid, match, [{"type": "OUTPUT", "port": out_port}], FLOW_PRIORITY)


def _compute_flow_entries(
    src_host: dict, dst_host: dict,
    src_dpid: int, dst_dpid: int, score_dpid: int,
) -> list[tuple]:
    """Return list of (dpid, match, actions, priority) for a bidirectional path."""
    src_ip = src_host["ip"]
    dst_ip = dst_host["ip"]
    src_sw = src_host["switch"]
    dst_sw = dst_host["switch"]
    src_port = src_host["port"]  # host's port on its edge switch
    dst_port = dst_host["port"]

    entries = []

    if src_sw == dst_sw:
        # ── same edge switch ──────────────────────────────────────────────
        dpid = src_dpid
        entries += [
            _fwd(dpid, {"dl_type": ETH_IP,  "nw_src": src_ip, "nw_dst": dst_ip, "nw_proto": 6}, dst_port),
            _fwd(dpid, {"dl_type": ETH_IP,  "nw_src": dst_ip, "nw_dst": src_ip, "nw_proto": 6}, src_port),
            _fwd(dpid, {"dl_type": ETH_ARP, "arp_spa": src_ip, "arp_tpa": dst_ip}, dst_port),
            _fwd(dpid, {"dl_type": ETH_ARP, "arp_spa": dst_ip, "arp_tpa": src_ip}, src_port),
        ]
    else:
        # ── cross-switch: src_edge → score → dst_edge ────────────────────
        score_src_port = SWITCH_TO_SCORE_PORT[src_sw]  # score port toward src
        score_dst_port = SWITCH_TO_SCORE_PORT[dst_sw]  # score port toward dst

        # src edge switch
        entries += [
            _fwd(src_dpid, {"dl_type": ETH_IP,  "nw_src": src_ip, "nw_dst": dst_ip, "nw_proto": 6}, UPLINK_PORT),
            _fwd(src_dpid, {"dl_type": ETH_IP,  "nw_src": dst_ip, "nw_dst": src_ip, "nw_proto": 6}, src_port),
            _fwd(src_dpid, {"dl_type": ETH_ARP, "arp_spa": src_ip, "arp_tpa": dst_ip}, UPLINK_PORT),
            _fwd(src_dpid, {"dl_type": ETH_ARP, "arp_spa": dst_ip, "arp_tpa": src_ip}, src_port),
        ]
        # score (core switch)
        entries += [
            _fwd(score_dpid, {"dl_type": ETH_IP,  "nw_src": src_ip, "nw_dst": dst_ip, "nw_proto": 6}, score_dst_port),
            _fwd(score_dpid, {"dl_type": ETH_IP,  "nw_src": dst_ip, "nw_dst": src_ip, "nw_proto": 6}, score_src_port),
            _fwd(score_dpid, {"dl_type": ETH_ARP, "arp_spa": src_ip, "arp_tpa": dst_ip}, score_dst_port),
            _fwd(score_dpid, {"dl_type": ETH_ARP, "arp_spa": dst_ip, "arp_tpa": src_ip}, score_src_port),
        ]
        # dst edge switch
        entries += [
            _fwd(dst_dpid, {"dl_type": ETH_IP,  "nw_src": src_ip, "nw_dst": dst_ip, "nw_proto": 6}, dst_port),
            _fwd(dst_dpid, {"dl_type": ETH_IP,  "nw_src": dst_ip, "nw_dst": src_ip, "nw_proto": 6}, UPLINK_PORT),
            _fwd(dst_dpid, {"dl_type": ETH_ARP, "arp_spa": src_ip, "arp_tpa": dst_ip}, dst_port),
            _fwd(dst_dpid, {"dl_type": ETH_ARP, "arp_spa": dst_ip, "arp_tpa": src_ip}, UPLINK_PORT),
        ]

    return entries


def _switches_on_path(src_sw: str, dst_sw: str) -> list[str]:
    if src_sw == dst_sw:
        return [src_sw]
    return [src_sw, "score", dst_sw]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "dpids": state.dpids}


@app.get("/topology")
async def get_topology():
    # Collect switches that carry at least one active flow
    active_switches: set[str] = set()
    for flow in state.flows.values():
        active_switches.update(flow.get("switches", []))

    nodes = []
    for name, info in state.hosts.items():
        nodes.append({
            "id": name, "type": "host",
            "ip": info["ip"], "app_count": info["app_count"],
        })
    for sw in ["score", "s1", "s2", "s3"]:
        nodes.append({"id": sw, "type": "switch", "active": sw in active_switches})

    links = []
    for src, dst in _TOPOLOGY_LINKS:
        active = src in active_switches or dst in active_switches
        links.append({"source": src, "target": dst, "active": active})

    return {"nodes": nodes, "links": links}


@app.get("/state")
async def get_state():
    return {
        "hosts": state.hosts,
        "apps": state.apps,
        "requirements": state.requirements,
        "flows": state.flows,
    }


# ── Deploy service ──────────────────────────────────────────────────────────

class DeployRequest(BaseModel):
    service: str


@app.post("/services/deploy")
async def deploy_service(req: DeployRequest):
    if req.service != "shop":
        return JSONResponse({"error": f"unknown service '{req.service}'"}, status_code=400)

    # Pick host for webserver
    ws_host = placement.pick_host(state.hosts)
    if ws_host is None:
        return JSONResponse({"error": "no hosts available for webserver"}, status_code=503)
    state.hosts[ws_host]["app_count"] += 1

    # Pick host for database (now considers updated app_count)
    db_host = placement.pick_host(state.hosts)
    if db_host is None:
        state.hosts[ws_host]["app_count"] -= 1
        return JSONResponse({"error": "no hosts available for database"}, status_code=503)
    state.hosts[db_host]["app_count"] += 1

    ws_id = f"web-{uuid.uuid4().hex[:6]}"
    db_id = f"db-{uuid.uuid4().hex[:6]}"
    db_ip = state.hosts[db_host]["ip"]

    logger.info("Deploying webserver→%s db→%s", ws_host, db_host)
    await asyncio.to_thread(kathara_ctl.start_app, ws_host, "webserver", {"DB_URL": f"http://{db_ip}:5001"})
    await asyncio.to_thread(kathara_ctl.start_app, db_host, "database", {})

    state.apps[ws_id] = {
        "app_id": ws_id, "service": req.service, "type": "webserver",
        "host": ws_host, "status": "running",
    }
    state.apps[db_id] = {
        "app_id": db_id, "service": req.service, "type": "database",
        "host": db_host, "status": "running",
    }
    state.save()

    return {
        "webserver_id": ws_id, "database_id": db_id,
        "ws_host": ws_host, "db_host": db_host,
    }


# ── Stop app ────────────────────────────────────────────────────────────────

@app.post("/apps/{app_id}/stop")
async def stop_app(app_id: str):
    if app_id not in state.apps:
        return JSONResponse({"error": "app not found"}, status_code=404)

    app_info = state.apps[app_id]

    # Remove every requirement that references this app
    stale_reqs = [
        rid for rid, r in list(state.requirements.items())
        if r["src_app"] == app_id or r["dst_app"] == app_id
    ]
    for rid in stale_reqs:
        await _delete_requirement(rid)

    await asyncio.to_thread(kathara_ctl.stop_app, app_info["host"], app_info["type"])
    state.hosts[app_info["host"]]["app_count"] = max(
        0, state.hosts[app_info["host"]]["app_count"] - 1
    )
    del state.apps[app_id]
    state.save()

    logger.info("Stopped app %s on %s", app_id, app_info["host"])
    return {"stopped": app_id}


# ── Requirements ────────────────────────────────────────────────────────────

class RequirementRequest(BaseModel):
    src_app_id: str
    dst_app_id: str


@app.post("/requirements")
async def add_requirement(req: RequirementRequest):
    if req.src_app_id not in state.apps:
        return JSONResponse({"error": "src_app not found"}, status_code=404)
    if req.dst_app_id not in state.apps:
        return JSONResponse({"error": "dst_app not found"}, status_code=404)

    if not state.dpids:
        try:
            await asyncio.to_thread(_discover_dpids_sync)
        except Exception as exc:
            return JSONResponse({"error": f"dpid discovery failed: {exc}"}, status_code=503)

    src_app = state.apps[req.src_app_id]
    dst_app = state.apps[req.dst_app_id]
    src_host = state.hosts[src_app["host"]]
    dst_host = state.hosts[dst_app["host"]]
    src_sw = src_host["switch"]
    dst_sw = dst_host["switch"]

    src_dpid = state.dpids.get(src_sw)
    dst_dpid = state.dpids.get(dst_sw)
    score_dpid = state.dpids.get("score")

    if not all([src_dpid, dst_dpid, score_dpid]):
        return JSONResponse({"error": "switch dpids unknown, lab may not be running"}, status_code=503)

    entries = _compute_flow_entries(src_host, dst_host, src_dpid, dst_dpid, score_dpid)
    switches = _switches_on_path(src_sw, dst_sw)

    flow_ids = []
    for dpid, match, actions, priority in entries:
        await ryu_client.add_flow(dpid, match, actions, priority)
        fid = f"f-{uuid.uuid4().hex[:8]}"
        state.flows[fid] = {
            "flow_id": fid,
            "src_ip": src_host["ip"],
            "dst_ip": dst_host["ip"],
            "dpid": dpid,
            "match": match,
            "actions": actions,
            "priority": priority,
            "switches": switches,
        }
        flow_ids.append(fid)

    req_id = f"req-{uuid.uuid4().hex[:6]}"
    state.requirements[req_id] = {
        "req_id": req_id,
        "src_app": req.src_app_id,
        "dst_app": req.dst_app_id,
        "flow_ids": flow_ids,
    }
    state.save()

    logger.info(
        "Requirement %s: %s(%s) → %s(%s), %d flows installed",
        req_id, req.src_app_id, src_host["ip"],
        req.dst_app_id, dst_host["ip"], len(flow_ids),
    )
    return {"req_id": req_id, "flow_ids": flow_ids}


@app.delete("/requirements/{req_id}")
async def remove_requirement(req_id: str):
    if req_id not in state.requirements:
        return JSONResponse({"error": "requirement not found"}, status_code=404)
    await _delete_requirement(req_id)
    state.save()
    logger.info("Removed requirement %s", req_id)
    return {"removed": req_id}


async def _delete_requirement(req_id: str):
    req = state.requirements.pop(req_id, None)
    if not req:
        return
    for fid in req.get("flow_ids", []):
        flow = state.flows.pop(fid, None)
        if flow:
            try:
                await ryu_client.delete_flow(flow["dpid"], flow["match"], flow["priority"])
            except Exception as exc:
                logger.warning("Flow delete failed for %s: %s", fid, exc)


# ── Flows ───────────────────────────────────────────────────────────────────

@app.get("/flows")
async def get_flows():
    try:
        ryu_flows = await ryu_client.get_all_flows(list(state.dpids.values()))
        return {"ryu_flows": ryu_flows, "local_flows": state.flows}
    except Exception as exc:
        return JSONResponse(
            {"error": str(exc), "local_flows": state.flows}, status_code=502
        )


# ── Admin ───────────────────────────────────────────────────────────────────

@app.post("/admin/discover")
async def discover_dpids():
    """Re-run dpid discovery (useful after lab restart)."""
    try:
        await asyncio.to_thread(_discover_dpids_sync)
        return {"dpids": state.dpids}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)


@app.post("/admin/reset")
async def reset_state():
    """Wipe in-memory state (does NOT stop running containers)."""
    state.hosts.update({k: {**v, "app_count": 0} for k, v in state.hosts.items()})
    state.apps.clear()
    state.requirements.clear()
    state.flows.clear()
    state.save()
    return {"status": "reset"}


# ── WebSocket log stream ─────────────────────────────────────────────────────

@app.websocket("/logs")
async def ws_logs(ws: WebSocket):
    await ws.accept()
    _ws_clients.append(ws)
    try:
        # Send buffered history first
        for line in _log_buffer:
            await ws.send_text(line)
        # Keep alive until client disconnects
        while True:
            await asyncio.sleep(30)
            await ws.send_text("")  # heartbeat
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        _ws_clients.remove(ws)


# ── Static GUI (production build) ────────────────────────────────────────────

_GUI_DIST = Path(__file__).parent.parent / "gui" / "dist"
if _GUI_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_GUI_DIST), html=True), name="gui")
