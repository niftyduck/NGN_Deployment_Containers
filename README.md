# NGN Deployment Containers

Web-based orchestration system for **Next Generation Networks (Prof. Michele Segata)**.

It runs a fixed Kathará SDN lab (tree topology, OVS switches, Ryu controller) and lets a user
deploy "services" (groups of fake apps) onto hosts through a React GUI. The orchestrator
automatically installs OpenFlow rules so that only apps which need to talk to each other can —
by default **no host can reach any other host** (fail-mode secure, no default flows).

---

## 1. Requirements

| Tool | Why | Notes |
|---|---|---|
| **Docker** (Desktop on Windows, with the Linux/WSL2 backend) | Builds and runs every Kathará container | Required to run `docker build` and by Kathará itself |
| **Kathará** | Network emulation engine | https://www.kathara.org/ |
| **Python 3.10+** | Runs the FastAPI orchestrator on your host machine | The Ryu *controller container* internally pins Python 3.9 — that's handled by `Dockerfile.controller`, not a requirement for your host |
| **Node.js 18+ and npm** | Builds/runs the React GUI (Vite) | |
| A POSIX-ish shell or PowerShell | To run `kathara`/`docker` commands | Examples in this README use PowerShell |

The two custom Docker images used in the lab are **not** pulled from a registry — you build them
locally once (see §3):

- `custom/ryu` — Debian Bullseye + Python 3.9 + Ryu (`Dockerfile.controller`)
- `custom/host` — `kathara/base` + Flask/requests pre-installed (`Dockerfile.host`)

> **Why a custom host image?** The lab hosts (`h1`–`h6`) have no default gateway/DNS — they are
> intentionally isolated on `10.0.0.0/24` with nothing else. `pip install` run at container
> *startup* can never reach PyPI from inside the lab, so Flask/requests are baked into the image
> at **build time** instead (when Docker runs on your machine, which does have internet access).

---

## 2. Ports / processes reference

| Port | What | Reachable from your machine (`localhost`)? |
|---|---|---|
| `8000` | Orchestrator — FastAPI REST API + `/logs` WebSocket | ✅ Yes |
| `5173` | GUI dev server (Vite, `npm run dev`) | ✅ Yes |
| `8080` | Ryu controller REST API (`ofctl_rest`) | ✅ Yes — `controller` is the only lab device with `bridged=true` + explicit port mapping in `lab.conf` |
| `6653` | OpenFlow control channel (switches ↔ Ryu) | ❌ No — internal to the lab's `CTRL` network (`20.0.0.0/24`) only |
| `5000` | `webserver.py` fake app | ❌ No — internal to the lab's `10.0.0.0/24` network only |
| `5001` | `database.py` fake app | ❌ No — internal only |
| `5002` | `auth.py` fake app | ❌ No — internal only |

The fake apps are **never** exposed on your machine's `localhost`. To reach them you must be
either inside another lab container with a permitting OpenFlow flow installed, or use
`kathara exec` to run a command inside a lab container (see §4).

Default host → switch → port map (`kathara-labs/shared/host_map.json`):

| Host | IP | Switch |
|---|---|---|
| h1 | 10.0.0.1 | s1 |
| h2 | 10.0.0.2 | s1 |
| h3 | 10.0.0.3 | s2 |
| h4 | 10.0.0.4 | s2 |
| h5 | 10.0.0.5 | s3 |
| h6 | 10.0.0.6 | s3 |

---

## 3. Running the project

Run these in order, each in its own terminal where noted.

### 3.1 Build the Docker images (once, or whenever a Dockerfile changes)

```powershell
cd C:\Users\tparl\PycharmProjects\NGN_Deployment_Containers
docker build -f Dockerfile.controller -t custom/ryu .
docker build -f Dockerfile.host -t custom/host .
```

### 3.2 Start the Kathará lab

```powershell
cd kathara-labs
kathara lstart
```

Wait ~5 seconds for OVS and Ryu to finish connecting.

### 3.3 Start the orchestrator (FastAPI)

```powershell
cd orchestrator
pip install -r requirements.txt   # first time only
uvicorn main:app --reload --port 8000
```

If the lab was just (re)started, the OVS datapath-ids are new/random, so tell the orchestrator
to rediscover them and start from a clean slate (in a separate terminal):

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/admin/reset"   -Method Post
Invoke-RestMethod -Uri "http://localhost:8000/admin/discover" -Method Post
```

### 3.4 Start the GUI (React + Vite)

```powershell
cd gui
npm install   # first time only
npm run dev
```

GUI: http://localhost:5173 — Orchestrator API: http://localhost:8000

### 3.5 Stop everything

```powershell
cd kathara-labs
kathara lclean
```

---

## 4. Useful commands

| Command | What it does |
|---|---|
| `kathara lstart` | Boot every device/collision-domain defined in `lab.conf` |
| `kathara lclean` | Tear down the whole lab |
| `kathara connect <device>` | Open an **interactive terminal** inside a running device (e.g. `kathara connect h1`) — best for live demos |
| `kathara exec <device> -- <cmd>` | Run a **one-off** command inside a device without opening a shell (e.g. `kathara exec h1 -- ss -tlnp`) |
| `kathara exec <device> -- cat /tmp/<app>.log` | Read the stdout/stderr log of a fake app started by the orchestrator |

Orchestrator REST API (base `http://localhost:8000`):

| Method & path | What it does |
|---|---|
| `GET /state` | Full snapshot: hosts, apps, requirements, flows |
| `GET /topology` | Graph data for the GUI |
| `POST /services/deploy` `{"service": "shop"}` | Deploy a service (`shop` = webserver+database, `banking` = webserver+auth+database) |
| `POST /apps/{app_id}/stop` | Stop an app and clean up its flows |
| `POST /requirements` `{"src_app_id", "dst_app_id"}` | Install the OpenFlow rules (TCP + ARP, both directions) allowing two apps to talk |
| `DELETE /requirements/{req_id}` | Remove those rules |
| `GET /flows` | Flows as seen by Ryu + the orchestrator's local bookkeeping |
| `POST /admin/reset` | Wipe in-memory state (use after restarting the lab) |
| `POST /admin/discover` | Re-read switch datapath-ids from Ryu (use after restarting the lab) |

---

## 5. How to check if two apps are actually communicating

Connectivity between two apps depends on **both**: the app process actually being up, **and**
an OpenFlow requirement existing between the two hosts. Telling these apart matters:

| What you see | Meaning |
|---|---|
| Immediate JSON/HTML response | ✅ Everything works — network flow installed *and* the app is up |
| `Connection refused` | Network is fine (packet reached the host), but **no process is listening** on that port — app crashed or never started |
| Timeout / no response | **No OpenFlow flow** allows that traffic — requirement missing (default-deny doing its job, or you targeted the wrong host pair) |

### Worked example

State: `shop` service deployed, webserver on `h1` (`10.0.0.1:5000`), database on `h2`
(`10.0.0.2:5001`). App ids and requirement id are random per deploy — substitute your own
(check `GET /state`).

**1. Before adding the requirement — confirm it fails:**

```powershell
cd kathara-labs
kathara exec h1 -- python3 -c "import requests; print(requests.get('http://10.0.0.1:5000', timeout=5).text)"
```
```
<h1>Web Server</h1><p>Error connecting to backend</p>
```
The webserver app itself tried to reach the database and timed out — no flow exists yet.

**2. Add the requirement (webserver → database):**

```powershell
$body = @{src_app_id="web-e2c7d4"; dst_app_id="db-33fca5"} | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8000/requirements -Method Post -ContentType "application/json" -Body $body
```

**3. Same test again — now it succeeds:**

```powershell
kathara exec h1 -- python3 -c "import requests; print(requests.get('http://10.0.0.1:5000', timeout=5).text)"
```
```
<h1>Web Server</h1><p>Got from DB: {'count': 3, 'rows': ['user_1', 'user_2', 'user_3']}</p>
```

### Live two-terminal demo (e.g. in front of the professor)

1. Open a terminal into the **server** side and tail its log — it will print a line the instant
   a request actually arrives:
   ```bash
   kathara connect h2
   tail -f /tmp/database.log
   ```
2. Open a second terminal into the **client** side and run the same request from §"Worked
   example" above, once *before* and once *after* adding the requirement. Before: nothing shows
   up in the `h2` terminal and the client times out. After: the request succeeds instantly and a
   new log line appears live in the `h2` terminal — a clear, simultaneous before/after.
