# GUI Guide

The GUI is a **React + Vite** single-page application (`gui/`). It has no router — it is a single page that polls the orchestrator every 3 seconds and reacts to state changes.

---

## How to run

```bash
# Development (hot-reload, talks to orchestrator at localhost:8000)
cd gui && npm install && npm run dev
# → http://localhost:5173

# Production build (served by FastAPI at localhost:8000)
cd gui && npm run build
# → gui/dist/ is then served automatically by the orchestrator
```

---

## File structure

```
gui/src/
├── main.jsx              entry point, mounts <App /> into #root
├── index.css             global dark-mode reset
├── api.js                all fetch() calls to the orchestrator
└── components/
    ├── TopologyGraph.jsx  D3 force-graph network visualisation
    ├── DeployPanel.jsx    deploy service, stop apps, add requirements
    └── FlowTable.jsx      table of active requirements + raw flow entries
```

---

## `api.js` — the HTTP layer

A thin wrapper around `fetch()`. All functions throw on non-2xx responses by reading `data.error` from the JSON body.

```javascript
const BASE = "http://localhost:8000"

getTopology()                        // GET /topology
getState()                           // GET /state
getFlows()                           // GET /flows
discoverDpids()                      // POST /admin/discover
deployService(service)               // POST /services/deploy
stopApp(appId)                       // POST /apps/{id}/stop
addRequirement(srcAppId, dstAppId)   // POST /requirements
deleteRequirement(reqId)             // DELETE /requirements/{id}
```

---

## `App.jsx` — state and wiring

This is the root component. It owns all shared state and connects everything together.

### State variables

```javascript
topology    // {nodes, links} from GET /topology — drives TopologyGraph
appState    // {hosts, apps, requirements, flows} from GET /state — drives panels
loading     // boolean — disables all buttons during any in-flight mutation
backendOk   // boolean — shown in the header as ● connected / ● backend offline
logs        // string[] — last 200 lines from the WebSocket log stream
```

### Polling

Every 3 seconds, `refresh()` fires `GET /topology` and `GET /state` in parallel and updates both state variables. If either call throws, `backendOk` is set to `false` and the header turns red.

```javascript
useEffect(() => {
  refresh()
  const id = setInterval(refresh, 3000)
  return () => clearInterval(id)
}, [refresh])
```

### WebSocket logs

On mount, a WebSocket connection is opened to `ws://localhost:8000/logs`. The backend replays the last 200 buffered log lines on connect, then streams new lines in real time. On disconnect (e.g. backend restart) the client automatically reconnects after 3 seconds.

### Mutation pattern (`mutate`)

All user actions (deploy, stop, add/remove requirement) go through the same wrapper:

```javascript
const mutate = async (fn) => {
  setLoading(true)
  try {
    const result = await fn()
    await refresh()   // re-fetch state immediately after any change
    return result
  } finally {
    setLoading(false)
  }
}
```

This ensures the UI always reflects the new backend state right after a mutation, without waiting for the next 3-second poll.

### Layout

```
┌─────────────────────────────────────────────────────┐
│  Header: title | connection status | re-discover btn │
├───────────────────────┬─────────────────────────────┤
│                       │  DeployPanel                │
│   TopologyGraph       │  FlowTable                  │
│   (62% width)         │  (38% width, scrollable)    │
│                       ├─────────────────────────────┤
│                       │  Log pane (150px, WebSocket)│
└───────────────────────┴─────────────────────────────┘
```

---

## `TopologyGraph.jsx` — network visualisation

Uses `react-force-graph-2d` (canvas-based). The simulation is disabled (`cooldownTicks={0}`) and every node is **pinned to a fixed position** defined in the `POSITIONS` map:

```javascript
const POSITIONS = {
  score: [0.50, 0.18],   // [x%, y%] relative to container size
  s1:    [0.22, 0.42],
  s2:    [0.50, 0.42],
  s3:    [0.78, 0.42],
  h1:    [0.12, 0.72],
  // ...
}
```

Percentages are multiplied by the actual container dimensions (tracked via `ResizeObserver`) to produce absolute `fx`/`fy` pin coordinates. This makes the graph resize correctly.

### Node colours

| Colour | Meaning |
|---|---|
| `#6e7681` grey | host with 0 apps |
| `#3fb950` green | host with 1 app |
| `#f78166` orange-red | host with 2 apps (full) |
| `#388bfd` blue | switch |

Switches are drawn as squares, hosts as circles. Labels appear below each node.

### Link colours

| Colour | Meaning |
|---|---|
| `#30363d` dark | link with no active flow |
| `#00d2ff` cyan | link with at least one active flow |

Active links also show animated particles flowing along them (`linkDirectionalParticles`).

A link is marked active if either of its two endpoints is a switch that appears in `flow.switches` for any currently installed flow. This is computed on the backend in `GET /topology` and sent as `link.active`.

---

## `DeployPanel.jsx` — user controls

Three sections in one component:

**Deploy Service**
A dropdown (currently only `shop`) and a Deploy button. On click calls `onDeploy(service)` which hits `POST /services/deploy`. On success shows a banner: `"Deployed: webserver → h1, db → h3"`.

**Running Apps**
Lists all apps from `appState.apps` where `status === "running"`. Each row shows the app id, type (colour-coded: green for webserver, purple for database), host name, IP, and service name. Each row has a Stop button that calls `onStop(appId)`.

**Add Connectivity Requirement**
Two dropdowns populated from running apps. The destination dropdown excludes the currently selected source. On click calls `onAddRequirement(srcId, dstId)` which hits `POST /requirements`. On success shows `"Flows installed: 12"`.

All three sections are hidden behind the same `loading` boolean — buttons disable during any in-flight request.

---

## `FlowTable.jsx` — requirements and flows

**Top section:** one row per requirement from `appState.requirements`. Shows:
- Requirement id (monospace)
- Path label: `h1(10.0.0.1) → h3(10.0.0.3)` (resolved from apps + hosts)
- Number of flow entries (green badge)
- Remove button → calls `onDeleteRequirement(reqId)` → `DELETE /requirements/{id}`

**Expandable section:** `▸ raw flow entries (12)` — a collapsed `<details>` showing every individual flow entry from `appState.flows`:
- `dpid` (blue)
- `src_ip → dst_ip`
- protocol badge: purple for ARP, blue for TCP
- output port

This is useful during demos to show that flows really are installed at the OpenFlow level.

---

## Dependency note

`react-force-graph-2d` is the only non-trivial dependency beyond React itself. It wraps the `force-graph` canvas library and handles the render loop internally. Node and link rendering is fully customised via `nodeCanvasObject` and `linkColor`/`linkWidth` callbacks.
