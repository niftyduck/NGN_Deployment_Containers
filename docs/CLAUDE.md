# CLAUDE.md — NGN Deployment Containers
**Course:** Next Generation Networks (AA 2025/2026) — Prof. Michele Segata  
**Project:** Automatic Deployment of Containers over an SDN network  
**Working directory:** `NGN_Deployment_Containers/` (this is the project root)

---

## What the project does

A web-based orchestration system that:
1. Runs a fixed Kathará SDN lab (tree topology, OVS switches, Ryu controller)
2. Lets the user deploy "services" (groups of fake apps) onto hosts via a React GUI
3. Automatically installs OpenFlow rules in the switches so only apps that need to communicate can do so
4. Lets the user stop apps and automatically cleans up the flows that are no longer needed

By default, **no host can talk to any other host** (fail-mode secure + no default flows). Connectivity only exists where the user explicitly adds a communication requirement.

---

## Network Topology

**2-level tree:** 1 core switch → 3 edge switches → 6 hosts (2 per edge switch = 3 "racks")

```
                    [controller]
                         |
                    20.0.0.100
                         |
                   [CTRL network: 20.0.0.0/24]
                    /    |    \    \
              20.0.0.1  .2   .3   .4
              [score]  [s1] [s2] [s3]
                 |      |    |    |
              (also   (eth1)(eth1)(eth1) ← uplink to score
               eth1,  (eth2)(eth2)(eth2) ← host port A
               eth2,  (eth3)(eth3)(eth3) ← host port B
               eth3)
                        |    |    |    |    |    |
                       h1   h2   h3   h4   h5   h6
                   10.0.0.1 .2   .3   .4   .5   .6
```

### Collision domains (lab.conf names)

| Domain | Who's on it |
|--------|------------|
| `CTRL` | controller eth0, score eth0, s1 eth0, s2 eth0, s3 eth0 |
| `CORE_S1` | score eth1 ↔ s1 eth1 |
| `CORE_S2` | score eth2 ↔ s2 eth1 |
| `CORE_S3` | score eth3 ↔ s3 eth1 |
| `S1_H1` | s1 eth2 ↔ h1 eth0 |
| `S1_H2` | s1 eth3 ↔ h2 eth0 |
| `S2_H3` | s2 eth2 ↔ h3 eth0 |
| `S2_H4` | s2 eth3 ↔ h4 eth0 |
| `S3_H5` | s3 eth2 ↔ h5 eth0 |
| `S3_H6` | s3 eth3 ↔ h6 eth0 |

### IP addresses

| Device | Interface | IP |
|--------|-----------|-----|
| controller | eth0 | 20.0.0.100/24 |
| score | eth0 | 20.0.0.1/24 |
| s1 | eth0 | 20.0.0.2/24 |
| s2 | eth0 | 20.0.0.3/24 |
| s3 | eth0 | 20.0.0.4/24 |
| h1 | eth0 | 10.0.0.1/24 |
| h2 | eth0 | 10.0.0.2/24 |
| h3 | eth0 | 10.0.0.3/24 |
| h4 | eth0 | 10.0.0.4/24 |
| h5 | eth0 | 10.0.0.5/24 |
| h6 | eth0 | 10.0.0.6/24 |

### Routing logic (for Ryu path computation)

Because it's a tree, every path between two hosts on different edge switches is exactly:
`host → edge_switch → score → edge_switch → host` (always 2 hops through score).

Hosts on the same edge switch: `host → edge_switch → host` (1 hop).

This makes path computation trivial — no Dijkstra needed, just check if src/dst share an edge switch.

---

## File/folder structure

```
NGN_Deployment_Containers/
├── CLAUDE.md                        ← this file
├── README.md                        ← how to run the demo (write last)
│
├── kathara-lab/                     ← Kathará lab files
│   ├── lab.conf                     ← topology definition
│   ├── controller.startup           ← starts Ryu inside the controller container
│   ├── score.startup                ← OVS setup for core switch
│   ├── s1.startup                   ← OVS setup for edge switch 1
│   ├── s2.startup
│   ├── s3.startup
│   ├── h1.startup … h6.startup      ← just sets IP address
│   └── shared/                      ← mounted at /shared in every container
│       └── controller/
│           └── sdn_controller.py    ← Ryu app (our custom controller)
│
├── orchestrator/                    ← FastAPI backend
│   ├── main.py                      ← FastAPI app, all API routes
│   ├── state.py                     ← in-memory state (hosts, apps, flows) + JSON snapshot
│   ├── placement.py                 ← picks which host to deploy an app on
│   ├── ryu_client.py                ← HTTP calls to Ryu REST API
│   ├── kathara_ctl.py               ← runs `kathara exec` to start/stop apps in containers
│   └── requirements.txt             ← fastapi, uvicorn, httpx
│
├── apps/                            ← fake demo applications (run inside host containers)
│   ├── webserver.py                 ← Flask HTTP server, fetches data from db on request
│   └── database.py                  ← Flask server that returns fake "DB rows" over HTTP
│
├── gui/                             ← React frontend (Vite project)
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── App.jsx
│       ├── components/
│       │   ├── TopologyGraph.jsx    ← D3 or react-force-graph network visualization
│       │   ├── DeployPanel.jsx      ← deploy service, add requirements, stop apps
│       │   └── FlowTable.jsx        ← table of active OpenFlow flows
│       └── api.js                   ← all fetch() calls to the orchestrator backend
│
├── Dockerfile.controller            ← Debian Bullseye + Python 3.9 + Ryu (see note)
└── scripts/
    ├── start.sh                     ← cd kathara-lab && kathara lstart
    └── stop.sh                      ← kathara lclean
```

---

## Tech stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Network emulation | Kathará (Docker-based) | Required |
| Switches | OVS with OpenFlow 1.3 | Standard SDN data plane |
| Controller | **Ryu** (Python) | Pure Python, REST API built-in, same as prof's examples |
| Orchestrator API | **FastAPI** (Python) | Simple REST API + WebSocket support |
| GUI | **React** (Vite) | User preference |
| Topology visualization | **D3.js** or `react-force-graph` | Network graph rendering |
| Fake apps | **Flask** (minimal) | Lightweight, stdlib-like |
| Controller ↔ Orchestrator | Ryu's built-in REST API (`ofctl_rest`) | No custom WebSocket needed |

---

## Dockerfile for the Ryu controller (CRITICAL — do not change Python version)

```dockerfile
# MUST use Debian Bullseye (Python 3.9). Ryu breaks on Python 3.10+ due to
# an eventlet/TimeoutError compatibility bug.
FROM debian:bullseye-slim
ARG DEBIAN_FRONTEND="noninteractive"
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-setuptools python3-dev gcc \
    iproute2 iputils-ping && rm -rf /var/lib/apt/lists/*
RUN ln -sf /usr/bin/python3 /usr/bin/python
RUN ln -sf /usr/bin/pip3 /usr/bin/pip
RUN pip install "eventlet==0.30.2"
RUN pip install "oslo.config==5.2.1"
RUN pip install ryu --no-build-isolation
WORKDIR /
```

This image is used in `lab.conf` as `controller[image]="custom/ryu"` after building it with:
```bash
docker build -f Dockerfile.controller -t custom/ryu .
```

For OVS switches, use the official `kathara/sdn` image (it has OVS pre-installed).
For hosts, use `kathara/base`.

---

## Step 1 — Kathará lab + OVS topology (no SDN yet)

**Goal:** `kathara lstart` boots all containers. Ping between hosts works (we'll temporarily use a learning switch to verify links, then disable it for SDN).

### lab.conf
```
score[0]="CTRL"
score[1]="CORE_S1"
score[2]="CORE_S2"
score[3]="CORE_S3"
score[image]="kathara/sdn"

s1[0]="CTRL"
s1[1]="CORE_S1"
s1[2]="S1_H1"
s1[3]="S1_H2"
s1[image]="kathara/sdn"

s2[0]="CTRL"
s2[1]="CORE_S2"
s2[2]="S2_H3"
s2[3]="S2_H4"
s2[image]="kathara/sdn"

s3[0]="CTRL"
s3[1]="CORE_S3"
s3[2]="S3_H5"
s3[3]="S3_H6"
s3[image]="kathara/sdn"

controller[0]="CTRL"
controller[image]="custom/ryu"
controller[bridged]=true
controller[port]="8080:8080/tcp"
controller[num_terms]=0

h1[0]="S1_H1/00:00:00:00:00:01"
h1[image]="kathara/base"
h2[0]="S1_H2/00:00:00:00:00:02"
h2[image]="kathara/base"
h2[num_terms]=0
h3[0]="S2_H3/00:00:00:00:00:03"
h3[image]="kathara/base"
h3[num_terms]=0
h4[0]="S2_H4/00:00:00:00:00:04"
h4[image]="kathara/base"
h4[num_terms]=0
h5[0]="S3_H5/00:00:00:00:00:05"
h5[image]="kathara/base"
h5[num_terms]=0
h6[0]="S3_H6/00:00:00:00:00:06"
h6[image]="kathara/base"
h6[num_terms]=0
```

### score.startup
```bash
ip addr add 20.0.0.1/24 dev eth0
/usr/share/openvswitch/scripts/ovs-ctl --system-id=random start
ovs-vsctl add-br score
ovs-vsctl set-fail-mode score secure
ovs-vsctl add-port score eth1
ovs-vsctl add-port score eth2
ovs-vsctl add-port score eth3
ovs-vsctl set bridge score protocols=[OpenFlow13]
ovs-vsctl set-controller score tcp:20.0.0.100:6653
```

### s1.startup (s2 and s3 are identical, change bridge name and IP)
```bash
ip addr add 20.0.0.2/24 dev eth0
/usr/share/openvswitch/scripts/ovs-ctl --system-id=random start
ovs-vsctl add-br s1
ovs-vsctl set-fail-mode s1 secure
ovs-vsctl add-port s1 eth1
ovs-vsctl add-port s1 eth2
ovs-vsctl add-port s1 eth3
ovs-vsctl set bridge s1 protocols=[OpenFlow13]
ovs-vsctl set-controller s1 tcp:20.0.0.100:6653
```

### h1.startup (h2–h6: same pattern, different IP)
```bash
ip addr add 10.0.0.1/24 dev eth0
```

### controller.startup
```bash
ip addr add 20.0.0.100/24 dev eth0
sleep 2
ryu-manager --ofp-tcp-listen-port 6653 --wsapi-port 8080 /shared/controller/sdn_controller.py ryu.app.ofctl_rest &
```

The `sleep 2` gives OVS time to start in the switch containers before the controller tries to receive connections. `ryu.app.ofctl_rest` is Ryu's built-in REST API — it exposes flow management at `http://20.0.0.100:8080` (reachable from the host machine because `[bridged]=true`).

**Verify step 1:** After `kathara lstart`, open a terminal on h1 and ping h2. It will FAIL (fail-mode secure = no flows). That's correct. If you temporarily change fail-mode to `standalone`, ping works — this proves the links are up.

---

## Step 2 — Ryu SDN controller (sdn_controller.py)

**Goal:** Controller manages all flows. By default zero traffic allowed. Orchestrator can add/remove flows via REST.

### File: `kathara-lab/shared/controller/sdn_controller.py`

The controller must:
1. On switch connect → install a table-miss rule that **drops** everything (not sends to controller). This enforces default-deny.
2. Expose a REST API the orchestrator can call to install/remove specific flows.

Use Ryu's built-in `ofctl_rest` app for flow management — it gives us `POST /stats/flowentry/add` and `POST /stats/flowentry/delete` out of the box, so we don't need to write custom REST handlers.

The orchestrator needs to know the **datapath ID (dpid)** of each switch. Get these after `lstart` by querying `GET http://20.0.0.100:8080/stats/switches`.

**Host map** — store this as a static JSON file at `kathara-lab/shared/host_map.json`. The orchestrator reads it to know which switch/port each host is connected to.

```json
{
  "h1": {"ip": "10.0.0.1", "mac": "00:00:00:00:00:01", "switch": "s1", "port": 2},
  "h2": {"ip": "10.0.0.2", "mac": "00:00:00:00:00:02", "switch": "s1", "port": 3},
  "h3": {"ip": "10.0.0.3", "mac": "00:00:00:00:00:03", "switch": "s2", "port": 2},
  "h4": {"ip": "10.0.0.4", "mac": "00:00:00:00:00:04", "switch": "s2", "port": 3},
  "h5": {"ip": "10.0.0.5", "mac": "00:00:00:00:00:05", "switch": "s3", "port": 2},
  "h6": {"ip": "10.0.0.6", "mac": "00:00:00:00:00:06", "switch": "s3", "port": 3}
}
```

Port numbering on each switch: eth1=port1 (uplink), eth2=port2 (host A), eth3=port3 (host B).
Port numbering on score: eth1=port1 (to s1), eth2=port2 (to s2), eth3=port3 (to s3).

### sdn_controller.py structure

```python
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3

class SDNController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        # Install a default DROP rule (priority 0, no actions = drop)
        datapath = ev.msg.datapath
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        # Empty instructions list = drop
        mod = parser.OFPFlowMod(datapath=datapath, priority=0, match=match, instructions=[])
        datapath.send_msg(mod)
```

The rest of flow management (add/delete specific flows) is handled by `ofctl_rest` which is loaded alongside this app.

**Verify step 2:** After `lstart`, ping between any two hosts fails. Then manually POST a flow via curl to allow h1→h2 and verify ping works. Then DELETE the flow and verify ping fails again.

```bash
# Example: allow h1 ↔ h2 (both directions, on switch s1)
# First get the dpid of s1: GET http://localhost:8080/stats/switches
# Then POST flows...
```

---

## Step 3+4 — Fake apps + Orchestrator backend

### Fake apps (apps/)

**webserver.py** — tiny Flask server that, on GET /, connects to the database app and returns its response.
```python
from flask import Flask
import requests, os
app = Flask(__name__)
DB_URL = os.environ.get("DB_URL", "http://10.0.0.2:5001")

@app.route("/")
def index():
    try:
        data = requests.get(DB_URL, timeout=2).json()
        return f"<h1>Web Server</h1><p>Got from DB: {data}</p>"
    except Exception as e:
        return f"<h1>Error connecting to DB</h1><p>{e}</p>", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
```

**database.py** — even simpler, returns fake rows.
```python
from flask import Flask, jsonify
app = Flask(__name__)

@app.route("/")
def data():
    return jsonify({"rows": ["user_1", "user_2", "user_3"], "count": 3})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
```

Both scripts are placed in `kathara-lab/shared/apps/` so they're accessible from any host container at `/shared/apps/`.

### Orchestrator state (state.py)

Keep everything in memory (+ save to `state.json` for crash recovery):

```python
# Hosts: fixed, loaded from host_map.json at startup
hosts = {
    "h1": {"ip": "10.0.0.1", "mac": "...", "switch": "s1", "port": 2, "app_count": 0},
    ...
}

# Apps: created when user deploys
apps = {}
# app_id → {"app_id": "web-1", "service": "shop", "type": "webserver",
#            "host": "h1", "pid": 1234, "status": "running"}

# Requirements: created when user adds communication rule
requirements = {}
# req_id → {"req_id": "r1", "src_app": "web-1", "dst_app": "db-1",
#            "flow_ids": ["f1", "f2", ...]}

# Flows: installed OpenFlow rules
flows = {}
# flow_id → {"flow_id": "f1", "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2",
#             "switches": ["s1"], "dpid_entries": [...]}
```

### Placement logic (placement.py)

```python
MAX_APPS_PER_HOST = 2

def pick_host(hosts: dict) -> str | None:
    # Prefer hosts in the same rack as other apps of the same service (rack affinity)
    # Fall back to least-loaded host
    available = [h for h, info in hosts.items() if info["app_count"] < MAX_APPS_PER_HOST]
    if not available:
        return None
    return min(available, key=lambda h: hosts[h]["app_count"])
```

### Kathará control (kathara_ctl.py)

```python
import subprocess

def start_app(host: str, app_type: str, env: dict) -> int:
    """Start an app in a host container. Returns PID."""
    env_str = " ".join(f'{k}="{v}"' for k, v in env.items())
    cmd = f"cd /shared/apps && {env_str} python3 {app_type}.py &"
    result = subprocess.run(
        ["kathara", "exec", host, "--", "bash", "-c", cmd],
        capture_output=True, text=True
    )
    # Parse PID from output if needed, or track via app name
    return result

def stop_app(host: str, app_type: str):
    """Kill the app process in the host container."""
    subprocess.run(
        ["kathara", "exec", host, "--", "bash", "-c", f"pkill -f {app_type}.py"],
        capture_output=True
    )
```

**Important:** `kathara exec` must be run from the `kathara-lab/` directory (or pass `-d` flag pointing to it).

### Ryu client (ryu_client.py)

```python
import httpx

RYU_BASE = "http://localhost:8080"  # bridged, reachable from host machine

async def get_switches() -> list:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{RYU_BASE}/stats/switches")
        return r.json()  # list of dpids

async def add_flow(dpid: int, match: dict, actions: list, priority: int = 100):
    flow = {"dpid": dpid, "priority": priority, "match": match, "actions": actions}
    async with httpx.AsyncClient() as client:
        await client.post(f"{RYU_BASE}/stats/flowentry/add", json=flow)

async def delete_flow(dpid: int, match: dict, priority: int = 100):
    flow = {"dpid": dpid, "priority": priority, "match": match}
    async with httpx.AsyncClient() as client:
        await client.post(f"{RYU_BASE}/stats/flowentry/delete", json=flow)
```

### Flow installation logic

When adding requirement src_app → dst_app:
1. Look up src host and dst host from `state.hosts`
2. Compute path: same edge switch? 1 hop. Different edge switch? 3 switches (edge → score → edge)
3. For each switch on the path, install a forward flow AND a reverse flow (TCP needs both directions)
4. Also install ARP pass-through on the same path (without ARP, TCP handshake fails)
5. Store all installed (dpid, match) tuples in `flows[flow_id]`

When removing requirement:
1. For each flow in `requirements[req_id]["flow_ids"]`, delete the flows from Ryu
2. Check if any other requirement still uses those switches/hosts before deleting
3. Update `app_count` if app is stopped

---

## Step 5 — FastAPI + React GUI

### FastAPI routes (orchestrator/main.py)

```
GET  /topology          → {nodes: [...], links: [...]} for graph visualization
GET  /state             → {hosts, apps, requirements, flows}
POST /services/deploy   → {service: "shop"} → deploys webserver + database, returns app_ids
POST /apps/{app_id}/stop → stops app, removes flows
POST /requirements      → {src_app_id, dst_app_id} → installs flows, returns req_id
DELETE /requirements/{req_id} → removes flows
GET  /flows             → all active flows from Ryu
WS   /logs              → WebSocket, streams log lines
```

FastAPI serves the React build as static files:
```python
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="gui/dist", html=True), name="gui")
```

### React GUI (gui/src/)

**App.jsx** — main layout: left panel (topology graph) + right panel (controls + flow table)

**TopologyGraph.jsx** — use `react-force-graph-2d` library (simpler than raw D3 for React). Nodes colored by load: grey (0 apps), green (1 app), orange (2/2 full). Edges glow when a flow is active on them.

**DeployPanel.jsx** — dropdown to pick service ("shop"), Deploy button, list of running apps with Stop buttons, Add Requirement form (pick src app, dst app → POST /requirements).

**FlowTable.jsx** — table showing active flows: flow_id, path (h1 → h2), protocol. Delete button calls DELETE /requirements/{req_id}.

**api.js** — thin wrapper:
```javascript
const BASE = "http://localhost:8000"
export const getState = () => fetch(`${BASE}/state`).then(r => r.json())
export const deployService = (service) => fetch(`${BASE}/services/deploy`, {
  method: "POST", headers: {"Content-Type": "application/json"},
  body: JSON.stringify({service})
}).then(r => r.json())
// ... etc
```

---

## Build/run order

```bash
# 1. Build the Ryu controller Docker image (do this once)
docker build -f Dockerfile.controller -t custom/ryu .

# 2. Start the Kathará lab
cd kathara-lab && kathara lstart

# 3. Wait ~5 seconds for OVS and Ryu to connect, then start the orchestrator
cd ../orchestrator && uvicorn main:app --reload --port 8000

# 4. In a separate terminal, start the React dev server
cd ../gui && npm install && npm run dev
# GUI available at http://localhost:5173
# (In production: npm run build, served by FastAPI at http://localhost:8000)

# 5. Stop everything
cd kathara-lab && kathara lclean
```

---

## Key implementation notes

- **Always install bidirectional flows + ARP flows.** If you only install h1→h2, the TCP SYN-ACK from h2→h1 gets dropped. Same for ARP — without it, hosts can't resolve MACs and TCP never starts. This is the most common SDN bug.
- **Switch port numbers:** In OVS, `eth1` inside the container = OpenFlow port 1, `eth2` = port 2, etc. Verify with `ovs-vsctl show` inside a switch container.
- **Ryu ofctl_rest dpid format:** dpids are integers. `GET /stats/switches` returns them. Store the mapping switch_name → dpid at startup.
- **kathara exec working directory:** must `cd kathara-lab/` before running `kathara exec`, or pass the lab path explicitly.
- **Flask in containers:** the `kathara/base` image has Python but not Flask. Either install Flask in the host `.startup` file (`pip install flask`) or use a custom image with Flask pre-installed. Simpler: add `pip install flask requests` to each `h*.startup`.
- **CORS:** FastAPI needs CORS middleware so the React dev server (port 5173) can call the API (port 8000). Add `from fastapi.middleware.cors import CORSMiddleware`.
- **State persistence:** save `state.json` after every mutation so a backend restart doesn't lose the topology state during the demo.
- **Demo services defined:**
  - `shop` = webserver (port 5000) + database (port 5001), requirement: webserver→database TCP/5001
  - Requirement proto is always TCP for the demo; flow match on `{"ipv4_src": ..., "ipv4_dst": ..., "ip_proto": 6}`

---

## Demo narrative (for the presentation)

1. `kathara lstart` — lab boots, all hosts isolated
2. GUI shows the tree topology, all hosts grey (0 apps)
3. Deploy `shop` → webserver lands on h1 (host turns green), database lands on h3 (different rack)
4. Try "Test connectivity" → fails (no flows yet)
5. Add requirement: webserver→database — flows installed on s1, score, s2
6. "Test connectivity" → webserver fetches DB, returns "3 rows". Flow table shows active flows, edges glow.
7. Deploy a second service → placement engine picks h2 (same rack as h1), h4
8. h1 turns orange (2/2 full). Next deploy would go to another rack.
9. Stop webserver → flows removed. Test connectivity fails again. h1 goes back to grey.
