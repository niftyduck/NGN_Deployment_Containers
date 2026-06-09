# LAB_GUIDE.md — NGN Deployment Containers

Complete walkthrough of the project: every file, every design decision, and every test you can run to verify the setup is working correctly.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Architecture overview](#2-architecture-overview)
3. [The Docker image — Dockerfile.controller](#3-the-docker-image----dockerfilecontroller)
4. [Kathará lab topology — lab.conf](#4-kathará-lab-topology----labconf)
5. [Switch startup scripts](#5-switch-startup-scripts)
6. [Host startup scripts](#6-host-startup-scripts)
7. [Controller startup script](#7-controller-startup-script)
8. [The Ryu SDN controller — sdn_controller.py](#8-the-ryu-sdn-controller----sdn_controllerpy)
9. [Static host map — host_map.json](#9-static-host-map----host_mapjson)
10. [Fake applications — shared/apps/](#10-fake-applications----sharedapps)
11. [Build and start the lab](#11-build-and-start-the-lab)
12. [Test plan — Step 1: topology sanity](#12-test-plan----step-1-topology-sanity)
13. [Test plan — Step 2: SDN default-deny](#13-test-plan----step-2-sdn-default-deny)
14. [Test plan — Step 3: manual flow insertion via Ryu REST](#14-test-plan----step-3-manual-flow-insertion-via-ryu-rest)
15. [Test plan — Step 4: bidirectional flows and ARP](#15-test-plan----step-4-bidirectional-flows-and-arp)
16. [Common problems and fixes](#16-common-problems-and-fixes)
17. [What comes next](#17-what-comes-next)

---

## 1. Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Docker Desktop | ≥ 4.x | Must be running before anything else |
| Kathará | ≥ 3.x | `pip install kathara` or from the official installer |
| Python | ≥ 3.9 (host) | For running the orchestrator later |
| curl / Postman | any | For testing the Ryu REST API |

Check they are installed:

```bash
docker --version
kathara --version
python3 --version
```

Kathará uses Docker under the hood: each node in the lab is a Docker container. The `kathara lstart` command reads `lab.conf` and spins up one container per declared device.

---

## 2. Architecture overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Host machine (your laptop)                                     │
│                                                                 │
│   ┌──────────────┐     HTTP :8080      ┌────────────────────┐  │
│   │ Orchestrator │ ──────────────────► │ Ryu REST API       │  │
│   │ (FastAPI)    │                     │ (inside controller  │  │
│   │ :8000        │                     │  container,         │  │
│   └──────────────┘                     │  bridged to host)  │  │
│          │                             └─────────┬──────────┘  │
│          │ kathara exec                           │ OpenFlow    │
│          ▼                                        │ :6653       │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │  Kathará network (Docker containers)                    │  │
│   │                                                         │  │
│   │  [controller] ── CTRL network (20.0.0.0/24) ──────┐    │  │
│   │                                                    │    │  │
│   │  [score/core] ──── [s1] ──── [h1] 10.0.0.1        │    │  │
│   │       │        │        └── [h2] 10.0.0.2          │    │  │
│   │       │        └── [s2] ──── [h3] 10.0.0.3         │    │  │
│   │       │                 └── [h4] 10.0.0.4           │    │  │
│   │       └────────── [s3] ──── [h5] 10.0.0.5           │    │  │
│   │                        └── [h6] 10.0.0.6            │    │  │
│   └─────────────────────────────────────────────────────┘  │  │
└─────────────────────────────────────────────────────────────────┘
```

### Two separate networks inside the lab

**Control network (CTRL, 20.0.0.0/24):** The controller, core switch (score), and all edge switches share this L2 domain. It is used exclusively for OpenFlow communication between switches and the Ryu controller. Hosts are NOT on this network.

**Data network (10.0.0.0/24):** The six hosts live here. Traffic between hosts crosses the OVS bridges. No IP routes are needed because all hosts are on the same /24 subnet; ARP resolves MACs directly.

### Why a 2-level tree?

The professor's spec requires a tree topology. A tree has exactly one path between any two leaves, which means:
- Path computation is trivial (no Dijkstra): same edge switch = 1 hop, different edge switches = 3 hops through score.
- There are no loops, so no spanning-tree complications.
- It mirrors real datacenter designs (ToR → aggregation → core).

### Why SDN / OpenFlow?

By default, OVS in `fail-mode secure` drops everything when no flow matches. The controller is the only entity that can install forwarding rules. This gives the orchestrator complete control over which applications can talk to which — the central requirement of the project.

---

## 3. The Docker image — `Dockerfile.controller`

```dockerfile
FROM debian:bullseye-slim
```

**Why Bullseye (Debian 11)?** Ryu depends on `eventlet`, which in turn monkey-patches the Python standard library's `TimeoutError`. In Python 3.10+, `TimeoutError` became a built-in alias for `OSError`, which breaks eventlet's patching. Debian Bullseye ships Python 3.9, which is the last version that works without a patched eventlet. This is a hard constraint — do not upgrade to Bookworm (Python 3.11) or the controller will crash on startup.

```dockerfile
RUN pip install "eventlet==0.30.2"
RUN pip install "oslo.config==5.2.1"
RUN pip install ryu --no-build-isolation
```

**Why pin eventlet to 0.30.2?** Later eventlet versions (0.31+) introduced changes that broke Ryu's internal use of `hub.sleep`. Version 0.30.2 is the last version known to be stable with Ryu.

**Why oslo.config?** Ryu depends on `oslo.config` (OpenStack's configuration library) but does not declare it as a dependency in newer pip metadata. Without explicitly installing it first, `pip install ryu` fails. Pinning `5.2.1` avoids further transitive dependency conflicts.

**Why `--no-build-isolation`?** Ryu's `setup.py` references packages that are already installed in the environment. Build isolation would create a clean build environment where those packages are missing, causing the build to fail.

**WORKDIR /**  
Ryu's startup script (`ryu-manager`) expects to run from `/`. Setting it here avoids having to `cd` in the startup script.

Build the image once, before the first `kathara lstart`:

```bash
docker build -f Dockerfile.controller -t custom/ryu .
```

This creates a local image named `custom/ryu`, which is what `lab.conf` references.

---

## 4. Kathará lab topology — `lab.conf`

Kathará's `lab.conf` uses a simple key-value syntax:

```
<device>[<interface_index>]="<collision_domain>"
<device>[<key>]=<value>
```

Every device that shares the same collision domain string is connected to the same virtual L2 segment (Kathará implements this with a Docker network).

### The collision domains

```
score[0]="CTRL"      → score's eth0 is on the CTRL management LAN
score[1]="CORE_S1"   → score's eth1 is a point-to-point link to s1
score[2]="CORE_S2"
score[3]="CORE_S3"
```

`CORE_S1`, `CORE_S2`, `CORE_S3` are point-to-point collision domains (only two devices share each one). Kathará still implements them as Docker networks, but logically they behave as direct cables.

```
s1[0]="CTRL"         → management (OpenFlow control plane)
s1[1]="CORE_S1"      → uplink to score
s1[2]="S1_H1"        → downlink to h1
s1[3]="S1_H2"        → downlink to h2
```

The interface index in `lab.conf` corresponds directly to `ethN` inside the container. `s1[0]` = `eth0`, `s1[1]` = `eth1`, etc. This is important because OVS port numbers mirror the ethN numbering: `eth1` = OVS port 1, `eth2` = OVS port 2.

### MAC address pinning for hosts

```
h1[0]="S1_H1/00:00:00:00:00:01"
```

The `/MAC` suffix tells Kathará to assign a specific MAC address to that interface. Without this, Docker assigns a random MAC at every `lstart`, which would break the static `host_map.json` that the orchestrator uses to build flow match rules. Pinning MACs makes the setup deterministic and reproducible.

### Images

| Device | Image | Reason |
|--------|-------|--------|
| score, s1, s2, s3 | `kathara/sdn` | Pre-installed OVS (Open vSwitch) |
| controller | `custom/ryu` | Our custom image with Ryu installed |
| h1–h6 | `kathara/base` | Minimal Debian, enough for Flask apps |

### Controller-specific options

```
controller[bridged]=true
controller[port]="8080:8080/tcp"
controller[num_terms]=0
```

`bridged=true` connects the controller container to the host machine's Docker bridge network in addition to the CTRL domain. This allows the orchestrator (running natively on your laptop) to reach the Ryu REST API at `http://localhost:8080` without having to `exec` into any container.

`port="8080:8080/tcp"` publishes Ryu's REST API port. Without this, the bridged interface would exist but the port would not be reachable from the host.

`num_terms=0` suppresses Kathará from opening a terminal window for the controller (it's managed programmatically, no interactive use needed).

---

## 5. Switch startup scripts

### `score.startup` — the core switch

```bash
ip addr add 20.0.0.1/24 dev eth0
```

Assigns an IP to eth0 (the CTRL domain interface) so that the controller can reach this switch for management purposes (though for OpenFlow the switch itself initiates the connection to the controller).

```bash
/usr/share/openvswitch/scripts/ovs-ctl --system-id=random start
```

Starts the OVS daemon (`ovsdb-server` + `ovs-vswitchd`). The `--system-id=random` generates a unique ID for this OVS instance. Without starting OVS first, all subsequent `ovs-vsctl` commands fail.

```bash
ovs-vsctl add-br score
```

Creates a new OVS bridge named `score`. The bridge name is arbitrary but matches the device name for clarity. The bridge is what actually forwards packets.

```bash
ovs-vsctl set-fail-mode score secure
```

**This is the critical security setting.** In `secure` mode, OVS drops all packets for which there is no matching flow entry, even if no controller is connected. The alternative is `standalone` mode (OVS acts as a learning switch when the controller is absent) — that would defeat the entire purpose of the project.

```bash
ovs-vsctl add-port score eth1
ovs-vsctl add-port score eth2
ovs-vsctl add-port score eth3
```

Attaches the physical interfaces to the bridge. `eth0` is intentionally excluded — it carries management traffic (CTRL domain) and must not be part of the forwarding bridge. Adding eth0 to the bridge would cause OVS to intercept its own management traffic.

```bash
ovs-vsctl set bridge score protocols=[OpenFlow13]
```

Locks the bridge to OpenFlow 1.3. OVS supports multiple OF versions; specifying 1.3 avoids version negotiation ambiguity and ensures we use OF 1.3 features (multiple tables, group tables, better match fields).

```bash
ovs-vsctl set-controller score tcp:20.0.0.100:6653
```

Tells OVS to connect to the Ryu controller at `20.0.0.100:6653`. Port 6653 is the IANA-assigned OpenFlow port (older setups used 6633, but 6653 is the standard since OF 1.3.1).

### `s1.startup`, `s2.startup`, `s3.startup`

Identical structure to `score.startup`, with different bridge names and IPs:

| Switch | IP | Bridge name |
|--------|----|-------------|
| s1 | 20.0.0.2/24 | s1 |
| s2 | 20.0.0.3/24 | s2 |
| s3 | 20.0.0.4/24 | s3 |

Each edge switch has 3 ports on its bridge: eth1 (uplink to score), eth2 (host A), eth3 (host B).

---

## 6. Host startup scripts

```bash
ip addr add 10.0.0.1/24 dev eth0
pip install flask requests -q &
```

Two lines per host:

1. **IP assignment:** Sets the data-plane IP. All six hosts are on 10.0.0.0/24. No default gateway is needed because they are all on the same subnet — ARP + the SDN flows handle reachability.

2. **Flask pre-installation:** The `kathara/base` image has Python 3 but not Flask. Running `pip install` in the startup script ensures Flask is available before the orchestrator tries to launch app processes inside the container. The `&` backgrounds the install so the startup script completes quickly. The `-q` flag suppresses pip's progress output. In a real scenario you would use a custom Docker image with Flask baked in, but for a demo the pip install on startup is simpler.

---

## 7. Controller startup script

```bash
ip addr add 20.0.0.100/24 dev eth0
```

Sets the controller's IP on the CTRL domain. Switches are configured to connect to `20.0.0.100:6653`, so this address is fixed.

```bash
sleep 2
```

Gives the OVS daemons in the switch containers time to finish starting before Ryu begins listening. Kathará starts all containers roughly in parallel; without this delay, Ryu would be ready before OVS and the switches' initial controller-connect attempts would fail. Two seconds is conservative — in practice OVS takes less than one second to start, but startup time varies under load.

```bash
ryu-manager --ofp-tcp-listen-port 6653 --wsapi-port 8080 \
    /shared/controller/sdn_controller.py ryu.app.ofctl_rest &
```

- `--ofp-tcp-listen-port 6653`: Ryu listens for OpenFlow connections on this port. Must match the port in the switch `set-controller` commands.
- `--wsapi-port 8080`: Ryu's built-in REST API (WSGI server) listens here. Accessible from the host machine because the controller container has `bridged=true` and `port="8080:8080/tcp"`.
- `/shared/controller/sdn_controller.py`: Our custom Ryu app. The `/shared/` directory is a Kathará convention — Kathará bind-mounts `kathara-labs/shared/` into every container at `/shared/`.
- `ryu.app.ofctl_rest`: Ryu's built-in REST app. Loading it alongside our app gives us `POST /stats/flowentry/add` and `POST /stats/flowentry/delete` without writing any REST handlers ourselves.
- `&`: Backgrounds the process so the startup script returns (Kathará expects startup scripts to terminate).

### Why load two Ryu apps at once?

Ryu's app model allows multiple app classes to coexist in the same process. Our `SDNController` handles the switch-connect event and installs the default-deny rule. `ofctl_rest` handles flow management HTTP requests. They share the same datapath objects and event bus internally, so flow entries installed via the REST API are applied through the same connected switches.

---

## 8. The Ryu SDN controller — `sdn_controller.py`

```python
class SDNController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
```

`OFP_VERSIONS` tells Ryu which OpenFlow versions this app supports. Setting it to OF 1.3 only prevents Ryu from connecting to switches that offer only OF 1.0 or 1.2, avoiding subtle compatibility bugs.

```python
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
```

`EventOFPSwitchFeatures` fires when a switch completes the OpenFlow handshake and sends its features reply. `CONFIG_DISPATCHER` means this handler runs during the configuration phase (before the switch is considered fully connected). This is the correct moment to install table-miss rules — before any data-plane packets arrive.

```python
        match = parser.OFPMatch()
        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=0,
            match=match,
            instructions=[]
        )
        datapath.send_msg(mod)
```

**Why priority 0?** OpenFlow selects the highest-priority matching flow. Traffic-specific flows installed by the orchestrator will have priority 100. The table-miss (catch-all) rule at priority 0 is matched only when nothing else matches, acting as the default action.

**Why empty `instructions=[]`?** In OpenFlow 1.3, a flow with an empty instruction set drops the packet silently. The alternatives would be `OFPIT_APPLY_ACTIONS` with `OFPAT_OUTPUT(CONTROLLER)` (send to controller for processing) or `OFPAT_OUTPUT(FLOOD)` (broadcast). We explicitly want neither — sending everything to the controller would be a CPU DoS, and flooding would bypass our access control. An empty instruction list is the correct way to express "drop".

**Why not use `OFPIT_CLEAR_ACTIONS`?** That instruction clears the action set for pipeline processing; it doesn't imply dropping. Empty instructions is more explicit.

### What the orchestrator will add later

When the user creates a communication requirement (e.g., webserver on h1 must reach database on h3), the orchestrator calls:

```
POST http://localhost:8080/stats/flowentry/add
```

with a JSON body like:

```json
{
  "dpid": 1,
  "priority": 100,
  "match": {"eth_type": 2048, "ipv4_src": "10.0.0.1", "ipv4_dst": "10.0.0.3", "ip_proto": 6},
  "actions": [{"type": "OUTPUT", "port": 1}]
}
```

These higher-priority flows override the catch-all drop rule for the specific traffic that is explicitly allowed.

---

## 9. Static host map — `host_map.json`

```json
{
  "h1": {"ip": "10.0.0.1", "mac": "00:00:00:00:00:01", "switch": "s1", "port": 2},
  ...
}
```

This file encodes the physical topology in a format the orchestrator can consume without running discovery protocols.

**Why static, not discovered?** For a demo with a fixed topology, discovering host locations dynamically (via packet-in events + MAC learning) adds significant complexity with no benefit. The topology never changes at runtime, so hardcoding it is correct.

**What each field means:**

| Field | Used for |
|-------|---------|
| `ip` | Flow match field (`ipv4_src` / `ipv4_dst`) |
| `mac` | ARP flow match field (`eth_src` / `eth_dst`) |
| `switch` | Identifies which edge switch the host is behind (and thus which dpid to program) |
| `port` | OVS output port for flows destined to this host |

**Port numbering:** OVS assigns port numbers sequentially as interfaces are added. Because the startup scripts always add eth1 first, then eth2, then eth3, the port numbers are deterministic: eth1=1, eth2=2, eth3=3. This matches the `port` values in `host_map.json`.

**Score's port-to-switch mapping** (needed when computing cross-rack paths):

| Score port | Connected switch |
|------------|-----------------|
| 1 | s1 |
| 2 | s2 |
| 3 | s3 |

---

## 10. Fake applications — `shared/apps/`

Both apps live in `kathara-labs/shared/apps/`, which Kathará mounts at `/shared/apps/` inside every host container. The orchestrator starts them with:

```bash
kathara exec h1 -- bash -c "cd /shared/apps && DB_URL=http://10.0.0.3:5001 python3 webserver.py &"
```

### `webserver.py`

A Flask app on port 5000. On any GET request, it fetches data from `DB_URL` and returns it as HTML. The `DB_URL` environment variable is injected at start time by the orchestrator (so the webserver knows which host the database is on, regardless of placement). If the database is unreachable (no flow installed), the HTTP request times out after 2 seconds and the webserver returns a 500 error — this is the "test connectivity fails" moment in the demo.

### `database.py`

A Flask app on port 5001. Always returns the same hardcoded JSON:

```json
{"rows": ["user_1", "user_2", "user_3"], "count": 3}
```

Its only purpose is to give the webserver something to fetch and display, making the connectivity test visually obvious.

---

## 11. Build and start the lab

### Step 1 — Build the controller image (once)

```bash
# Run from the project root (NGN_Deployment_Containers/)
docker build -f Dockerfile.controller -t custom/ryu .
```

This takes 2–5 minutes on first run (downloads Debian base layer + installs Python packages). Subsequent builds are cached.

Verify the image exists:

```bash
docker images custom/ryu
```

Expected output:

```
REPOSITORY   TAG       IMAGE ID       CREATED        SIZE
custom/ryu   latest    <hash>         <N> minutes ago   ~600MB
```

### Step 2 — Start the lab

```bash
cd kathara-labs
kathara lstart
```

Kathará reads `lab.conf` and starts one container per device. You will see output like:

```
Starting h1...
Starting h2...
...
Starting controller...
```

The `--noterminals` flag can suppress xterm windows if you don't want them:

```bash
kathara lstart --noterminals
```

### Step 3 — Wait for OVS + Ryu handshake

Wait ~5 seconds after `lstart`. During this time:
1. OVS daemons start inside each switch container
2. The controller runs `sleep 2`, then launches Ryu
3. Each switch's OVS connects to Ryu at `20.0.0.100:6653`
4. Ryu fires `EventOFPSwitchFeatures` for each switch
5. `switch_features_handler` installs the default-deny rule on each switch

### Step 4 — Stop the lab

```bash
kathara lclean
```

This stops and removes all containers. OVS state is lost (ephemeral). The next `lstart` starts completely fresh.

---

## 12. Test plan — Step 1: topology sanity

**Goal:** Verify that all containers are running and the network interfaces are configured correctly.

### 12.1 — List running containers

```bash
docker ps --filter "name=kathara"
```

You should see containers named something like `kathara_<labname>_h1`, `kathara_<labname>_score`, etc. Count them: you expect 11 containers (controller + score + s1 + s2 + s3 + h1–h6).

### 12.2 — Check host IP addresses

```bash
kathara exec h1 -- ip addr show eth0
kathara exec h3 -- ip addr show eth0
```

Expected:
```
h1: inet 10.0.0.1/24
h3: inet 10.0.0.3/24
```

### 12.3 — Check switch management IPs

```bash
kathara exec s1 -- ip addr show eth0
```

Expected: `inet 20.0.0.2/24`

### 12.4 — Check OVS bridge is up

```bash
kathara exec s1 -- ovs-vsctl show
```

Expected output (abbreviated):
```
Bridge s1
    Controller "tcp:20.0.0.100:6653"
        is_connected: true       ← THIS IS CRITICAL
    fail_mode: secure
    Port eth1
        Interface eth1
    Port eth2
        Interface eth2
    Port eth3
        Interface eth3
    Port s1
        Interface s1
            type: internal
```

If `is_connected: false` after 10 seconds, the controller is not reachable. See [§16 Common problems](#16-common-problems-and-fixes).

### 12.5 — Verify MAC pinning

```bash
kathara exec h1 -- ip link show eth0
```

The MAC should be exactly `00:00:00:00:00:01`. If it's random, the `lab.conf` MAC pinning syntax (`S1_H1/00:00:00:00:00:01`) was not parsed correctly — check for typos.

### 12.6 — Temporarily verify links with standalone mode

To confirm the cables are connected (independent of SDN), temporarily change one switch to `standalone`:

```bash
kathara exec s1 -- ovs-vsctl set-fail-mode s1 standalone
```

Now ping between h1 and h2 (same edge switch, so only s1 is involved):

```bash
kathara exec h1 -- ping -c 3 10.0.0.2
```

This should work because standalone mode makes OVS act as a learning switch. Restore fail-mode secure:

```bash
kathara exec s1 -- ovs-vsctl set-fail-mode s1 secure
```

And flush the learned flows:

```bash
kathara exec s1 -- ovs-ofctl del-flows s1
```

---

## 13. Test plan — Step 2: SDN default-deny

**Goal:** Verify that with no flows installed, all traffic is dropped.

### 13.1 — Ping between hosts (should fail)

```bash
kathara exec h1 -- ping -c 3 -W 1 10.0.0.2
```

Expected: `3 packets transmitted, 0 received, 100% packet loss`

Try across racks too:

```bash
kathara exec h1 -- ping -c 3 -W 1 10.0.0.3
```

Same result. If any ping succeeds, the fail-mode or default-deny rule is not working.

### 13.2 — Query Ryu for the installed flows

From your host machine (works because of `bridged=true` + port 8080):

```bash
# Get the list of all connected switches (returns dpids)
curl -s http://localhost:8080/stats/switches | python3 -m json.tool
```

Expected output: a JSON array of integers, one per switch, e.g.:

```json
[1, 2, 3, 4]
```

These are the datapath IDs (dpids). The order is not guaranteed.

```bash
# Get flows on switch with dpid 1
curl -s http://localhost:8080/stats/flow/1 | python3 -m json.tool
```

Expected: one flow entry — the default-deny rule at priority 0:

```json
[
  {
    "priority": 0,
    "match": {},
    "actions": [],
    "packet_count": <N>,
    "byte_count": <N>
  }
]
```

If you see no flows, the `switch_features_handler` did not fire. If you see multiple flows or a flow with actions, something else installed flows (a leftover from a previous `lstart` cycle — do `kathara lclean` and restart).

### 13.3 — Verify the Ryu controller is connected to all 4 switches

```bash
curl -s http://localhost:8080/stats/switches | python3 -m json.tool
```

You need exactly 4 dpids (score + s1 + s2 + s3). If fewer, some switches did not connect. Check `ovs-vsctl show` on the missing switch for `is_connected: false`.

---

## 14. Test plan — Step 3: manual flow insertion via Ryu REST

**Goal:** Manually install flows via the Ryu REST API and verify connectivity is restored — this is exactly what the orchestrator will do programmatically.

We will allow ping between h1 (10.0.0.1) and h2 (10.0.0.2). Both are behind s1.

### 14.1 — Find the dpid of s1

```bash
curl -s http://localhost:8080/stats/switches
# e.g. returns [1, 2, 3, 4]
```

To find which dpid corresponds to s1, query all switches and read the datapath desc:

```bash
for dpid in 1 2 3 4; do
  echo "=== dpid $dpid ==="
  curl -s http://localhost:8080/stats/desc/$dpid | python3 -m json.tool
done
```

Alternatively, check inside the container:

```bash
kathara exec s1 -- ovs-vsctl get bridge s1 datapath-id
```

This returns the dpid as a hex string (e.g., `"0000000000000001"`). Convert to decimal: `0x0000000000000001 = 1`.

For this example, assume s1 has dpid `1`.

### 14.2 — Install ICMP flows (both directions)

ICMP is IP protocol 1. We need flows in both directions on s1.

**Forward: h1 → h2** (h2 is on port 3 of s1)

```bash
curl -s -X POST http://localhost:8080/stats/flowentry/add \
  -H "Content-Type: application/json" \
  -d '{
    "dpid": 1,
    "priority": 100,
    "match": {
      "eth_type": 2048,
      "ipv4_src": "10.0.0.1",
      "ipv4_dst": "10.0.0.2",
      "ip_proto": 1
    },
    "actions": [{"type": "OUTPUT", "port": 3}]
  }'
```

**Reverse: h2 → h1** (h1 is on port 2 of s1)

```bash
curl -s -X POST http://localhost:8080/stats/flowentry/add \
  -H "Content-Type: application/json" \
  -d '{
    "dpid": 1,
    "priority": 100,
    "match": {
      "eth_type": 2048,
      "ipv4_src": "10.0.0.2",
      "ipv4_dst": "10.0.0.1",
      "ip_proto": 1
    },
    "actions": [{"type": "OUTPUT", "port": 2}]
  }'
```

**Note:** `eth_type: 2048` is `0x0800` = IPv4. This is required because OVS needs the Ethernet type to decode the IP header fields.

### 14.3 — Try the ping (still failing — ARP is missing!)

```bash
kathara exec h1 -- ping -c 3 -W 2 10.0.0.2
```

This will still fail. The reason is that before ICMP can flow, h1 needs to resolve h2's MAC address via ARP. ARP is a separate Ethernet protocol (eth_type `0x0806`) and our flows only match IPv4. See next section.

---

## 15. Test plan — Step 4: bidirectional flows and ARP

**Goal:** Understand and fix the ARP problem, then achieve a working ping.

### Why ARP is required

When h1 pings h2 for the first time:
1. h1 checks its ARP cache — no entry for 10.0.0.2
2. h1 sends an ARP request: broadcast `"Who has 10.0.0.2?"`
3. OVS receives this Ethernet frame on port 2 (h1's port)
4. OVS looks for a matching flow — no flow matches ARP (eth_type 0x0806), hits the default-deny rule
5. ARP request is dropped
6. h1 never learns h2's MAC → ICMP packet is never sent

### 15.1 — Install ARP flows

ARP does not have src/dst IP in the standard OF match fields at the Ethernet level. Use `arp_spa` (ARP sender protocol address) and `arp_tpa` (ARP target protocol address):

**ARP h1 → h2 direction (includes broadcast requests from h1):**

```bash
curl -s -X POST http://localhost:8080/stats/flowentry/add \
  -H "Content-Type: application/json" \
  -d '{
    "dpid": 1,
    "priority": 100,
    "match": {
      "eth_type": 2054,
      "arp_spa": "10.0.0.1",
      "arp_tpa": "10.0.0.2"
    },
    "actions": [{"type": "OUTPUT", "port": 3}]
  }'
```

**ARP h2 → h1 direction (includes h2's reply):**

```bash
curl -s -X POST http://localhost:8080/stats/flowentry/add \
  -H "Content-Type: application/json" \
  -d '{
    "dpid": 1,
    "priority": 100,
    "match": {
      "eth_type": 2054,
      "arp_spa": "10.0.0.2",
      "arp_tpa": "10.0.0.1"
    },
    "actions": [{"type": "OUTPUT", "port": 2}]
  }'
```

`eth_type: 2054` is `0x0806` = ARP.

**Note on ARP broadcasts:** ARP requests are sent to the Ethernet broadcast address (`ff:ff:ff:ff:ff:ff`), but the `arp_tpa` is the unicast IP being queried. OVS matches on `arp_tpa` regardless of the Ethernet destination, so this flow correctly catches broadcast ARP requests directed at 10.0.0.2.

### 15.2 — Try the ping again

```bash
kathara exec h1 -- ping -c 5 10.0.0.2
```

Expected:
```
5 packets transmitted, 5 received, 0% packet loss
rtt min/avg/max = X/X/X ms
```

### 15.3 — Cross-rack test (h1 → h3, different edge switches)

This requires flows on 3 switches: s1, score, s2.

For traffic from h1 (s1 port 2) to h3 (s2 port 2):
- **s1:** receive on port 2 → output port 1 (uplink to score)
- **score:** receive on port 1 (from s1) → output port 2 (toward s2)
- **s2:** receive on port 1 (from score) → output port 2 (h3's port)

And the reverse:
- **s2:** receive on port 2 → output port 1
- **score:** receive on port 2 → output port 1
- **s1:** receive on port 1 → output port 2

Install all 6 IPv4 flows + 6 ARP flows (same pattern, three times). This is exactly what the orchestrator automates.

### 15.4 — Verify flows are visible in Ryu

```bash
curl -s http://localhost:8080/stats/flow/1 | python3 -m json.tool
```

You should now see the default-deny (priority 0) plus all the flows you added (priority 100). The `packet_count` field increments with each matching packet — a useful live debugging tool.

### 15.5 — Delete flows and verify default-deny resumes

```bash
curl -s -X POST http://localhost:8080/stats/flowentry/delete \
  -H "Content-Type: application/json" \
  -d '{
    "dpid": 1,
    "priority": 100,
    "match": {
      "eth_type": 2048,
      "ipv4_src": "10.0.0.1",
      "ipv4_dst": "10.0.0.2",
      "ip_proto": 1
    }
  }'
```

Repeat for all installed flows. Then:

```bash
kathara exec h1 -- ping -c 3 -W 1 10.0.0.2
```

Must fail again. This confirms the orchestrator's flow removal logic will work correctly.

---

## 16. Common problems and fixes

### OVS `is_connected: false` after startup

**Cause:** The controller was not yet listening when OVS tried to connect, or there's a firewall/network issue.

**Fix:** OVS will retry the controller connection on its own every few seconds. Wait up to 30 seconds and run `ovs-vsctl show` again. If it never connects:

1. From inside a switch: `ping 20.0.0.100` — if this fails, the CTRL domain is broken (check `lab.conf` interface assignments).
2. From inside the controller: `ps aux | grep ryu` — verify ryu-manager is running.
3. Check that the switch startup script uses the same port (6653) that Ryu listens on.

### `curl http://localhost:8080` — connection refused

**Cause:** The controller container's `bridged=true` or port mapping is not effective.

**Fix:**
1. Verify the port mapping: `docker ps --filter "name=controller"` — look for `0.0.0.0:8080->8080/tcp` in the PORTS column.
2. If missing, the `lab.conf` line `controller[port]="8080:8080/tcp"` was not parsed. Check for quotes and syntax.
3. Ryu might have crashed on startup. Check logs: `docker logs <controller_container_name>`.

### Ryu crashes on startup (ImportError or AttributeError around TimeoutError)

**Cause:** Wrong Python version in the Docker image (Python 3.10+ breaks eventlet).

**Fix:** Rebuild `Dockerfile.controller` — ensure it still uses `FROM debian:bullseye-slim` (Bullseye = Python 3.9). Never upgrade the base image.

### Ping works in standalone mode but not SDN mode

**Cause:** Either the ARP flows are missing, or the IPv4 flows are missing in one direction.

**Debug:**
```bash
kathara exec h1 -- ping -c 1 -W 2 10.0.0.2
# Then immediately:
curl -s http://localhost:8080/stats/flow/1 | python3 -m json.tool
```

Check the `packet_count` on each flow. The ARP flow should have incremented. If `packet_count` is 0 on ARP flows, ARP is not reaching s1 (link issue). If ARP packet_count is > 0 but ICMP is 0, the ARP reply went through but ICMP is not matching (wrong IP in flow match).

### `kathara exec` hangs

**Cause:** The container is starting up (startup script still running pip install).

**Fix:** Wait 30–60 seconds for `pip install flask requests` to complete in the background, then retry.

### Flask install fails inside host container (no internet)

**Cause:** The `kathara/base` container has no internet access (no bridged interface, no NAT).

**Fix:** Add `h1[bridged]=true` to `lab.conf` temporarily for testing, or use a custom base image with Flask pre-installed (better for production demo):

```dockerfile
FROM kathara/base
RUN pip install flask requests
```

Build as `custom/host` and change `h*.image` in `lab.conf` accordingly.

---

## 17. What comes next

With the kathara-lab verified, the next components to build are:

1. **Orchestrator (FastAPI backend)** — `orchestrator/` directory
   - `state.py`: in-memory store for hosts, apps, requirements, flows
   - `placement.py`: picks which host to deploy an app on
   - `ryu_client.py`: wraps the Ryu REST API calls, including ARP + bidirectional flow logic
   - `kathara_ctl.py`: runs `kathara exec` to start/stop Flask apps in containers
   - `main.py`: FastAPI routes (`/topology`, `/state`, `/services/deploy`, `/requirements`, etc.)

2. **React GUI** — `gui/` directory
   - `TopologyGraph.jsx`: force-directed graph of the network, nodes colored by load
   - `DeployPanel.jsx`: deploy a service, add requirements, stop apps
   - `FlowTable.jsx`: live view of active flows

The key correctness invariant to remember throughout: **every new requirement must install 6 match rules on same-rack paths (3 IPv4 + 3 ARP × 2 directions on 1 switch) and 12 match rules on cross-rack paths (same × 3 switches)**. Getting this wrong is the #1 SDN bug.
