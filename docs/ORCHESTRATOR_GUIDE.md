# Orchestrator Guide

The orchestrator is a **FastAPI** application (`orchestrator/`) that sits between the GUI and the Kathará network lab. It manages application lifecycle, computes OpenFlow paths, and drives Ryu via its REST API.

---

## How it starts

```
uvicorn main:app --port 8000
```

On startup (`on_startup` in `main.py`) it:
1. Loads persisted state from `state.json` (or initialises fresh state from `host_map.json`)
2. Tries to discover the OpenFlow dpid of each switch by running `ovs-vsctl get bridge <name> datapath-id` inside each switch container via `kathara exec`

If Kathará is not running at that moment, dpid discovery is skipped with a warning — it can be triggered later via `POST /admin/discover`.

---

## Module by module

### `state.py` — in-memory store

Holds four dictionaries that represent everything the orchestrator knows:

```
hosts         → loaded from host_map.json, tracks app_count per host
apps          → running app instances (id, type, host, status)
requirements  → connectivity rules (src_app, dst_app, list of flow_ids)
flows         → individual OpenFlow entries (dpid, match, actions)
dpids         → switch name → datapath id (integer)
```

`save()` serialises all five dicts to `state.json`. `load()` reads it back. This means a backend restart does not lose state during a demo.

`host_map.json` is the source of truth for the static topology (which host is on which switch, which port, what IP/MAC).

---

### `placement.py` — host selection

```python
MAX_APPS_PER_HOST = 2

def pick_host(hosts) -> str | None:
    available = [h for h in hosts if hosts[h]["app_count"] < MAX_APPS_PER_HOST]
    return min(available, key=lambda h: hosts[h]["app_count"])
```

Always picks the **least-loaded** available host. Called twice per `POST /services/deploy` — once for the webserver, once for the database — so the two apps naturally spread across different hosts (the first call increments `app_count` before the second call runs).

---

### `kathara_ctl.py` — container control

Wraps `kathara exec` to run commands inside containers:

```
get_dpid(switch_name)            → reads OVS datapath-id, returns int
start_app(host, app_type, env)   → runs python3 <app_type>.py in background
stop_app(host, app_type)         → pkill -f <app_type>.py
```

All commands run with `cwd=LAB_DIR` (`kathara-labs/`), which is required by Kathará to know which lab to target.

`start_app` redirects stdout/stderr to `/tmp/<app_type>.log` inside the container and backgrounds the process with `&`, so `kathara exec` returns immediately.

---

### `ryu_client.py` — Ryu REST API

Talks to Ryu's built-in `ofctl_rest` app at `http://localhost:8080` (reachable because the controller container is started with `[bridged]=true`).

| Function | Endpoint | Purpose |
|---|---|---|
| `get_switches()` | `GET /stats/switches` | list of dpids |
| `add_flow(dpid, match, actions, priority)` | `POST /stats/flowentry/add` | install one flow |
| `delete_flow(dpid, match, priority)` | `POST /stats/flowentry/delete_strict` | remove exact match |
| `get_all_flows(dpid_list)` | `GET /stats/flow/<dpid>` | dump all flows |

`delete_strict` is used (not `delete`) because it matches on priority as well as fields, so it only removes the exact entry we installed.

---

### `main.py` — API routes and flow logic

#### Flow computation (`_compute_flow_entries`)

Given a source and destination host, this function returns a list of `(dpid, match, actions, priority)` tuples that must be installed to allow TCP traffic between them. It always installs:

- **Bidirectional TCP flows** — both `src→dst` and `dst→src`, because TCP SYN-ACK must return
- **Bidirectional ARP flows** — both directions, because without ARP the hosts cannot resolve each other's MAC address and TCP never starts

**Same edge switch** (e.g. h1 ↔ h2, both on s1): 4 flow entries on s1 only.

**Different edge switches** (e.g. h1 ↔ h3, s1 → score → s2): 12 flow entries across 3 switches:

```
s1:    src→dst: forward out uplink (port 1)
       dst→src: forward out host port
score: src→dst: forward out port toward s2
       dst→src: forward out port toward s1
s2:    src→dst: forward out dst host port
       dst→src: forward out uplink (port 1)
```
(×2 for ARP + TCP in each direction)

Port numbering (verified in OVS): `eth1=port1`, `eth2=port2`, `eth3=port3`. On edge switches port 1 is always the uplink to score; ports 2 and 3 connect to the two hosts.

#### API routes

| Method | Path | What it does |
|---|---|---|
| `GET` | `/health` | returns ok + current dpids |
| `GET` | `/topology` | nodes + links with active-flow annotations for the graph |
| `GET` | `/state` | full state dump (hosts, apps, requirements, flows) |
| `POST` | `/services/deploy` | picks two hosts, starts webserver + database via kathara_ctl, records apps |
| `POST` | `/apps/{id}/stop` | removes all requirements that reference this app, stops the process, decrements app_count |
| `POST` | `/requirements` | computes flow entries, installs them via ryu_client, records requirement |
| `DELETE` | `/requirements/{id}` | deletes all flow entries for this requirement from Ryu and from state |
| `GET` | `/flows` | merges local state with live Ryu dump |
| `POST` | `/admin/discover` | re-runs dpid discovery (use after lab restart) |
| `POST` | `/admin/reset` | clears in-memory state without touching containers |
| `WS` | `/logs` | streams log lines to the GUI; also replays the last 200 lines to a new connection |

#### Static file serving

When `gui/dist/` exists (after `npm run build`), FastAPI serves it at `/`. This means in production a single `uvicorn main:app --port 8000` serves both the API and the GUI.

---

## Data flow — deploy + connect example

```
User clicks "Deploy shop"
  → POST /services/deploy
    → placement.pick_host()  → h1 (webserver)
    → placement.pick_host()  → h3 (database, h1 now has app_count=1)
    → kathara_ctl.start_app("h1", "webserver", {"DB_URL": "http://10.0.0.3:5001"})
    → kathara_ctl.start_app("h3", "database", {})
    → state.apps["web-xxxx"] = {...}  /  state.apps["db-xxxx"] = {...}
    → state.save()

User clicks "Install Flows" (web-xxxx → db-xxxx)
  → POST /requirements  {src_app_id: "web-xxxx", dst_app_id: "db-xxxx"}
    → src_host = h1 (s1, port2, 10.0.0.1)  /  dst_host = h3 (s2, port2, 10.0.0.3)
    → _compute_flow_entries() → 12 tuples (s1 × 4, score × 4, s2 × 4)
    → for each: ryu_client.add_flow(dpid, match, actions, 100)
    → state.flows["f-xxxxxxxx"] = {...}  (×12)
    → state.requirements["req-xxxxxx"] = {flow_ids: [...12 ids]}
    → state.save()
```
