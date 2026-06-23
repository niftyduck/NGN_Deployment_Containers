
""" This script handles the state of the network from the orchestrator's
    point of view. Initializes the hosts by reading host_map.json and
    copies the content into state.json, which is updated live.

    It's just a set of utils for initialization, loading and saving
    the network info in main.py of the orchestrator."""

import json
from pathlib import Path

# Static config file describing the topology
HOST_MAP_PATH = Path(__file__).parent.parent / "kathara-labs" / "shared" / "host_map.json"

# Live runtime state
STATE_PATH = Path(__file__).parent / "state.json"

# For each host entry in host_map.json, it adds "app_count": 0
def _init_hosts() -> dict:
    with open(HOST_MAP_PATH) as f:
        raw = json.load(f)

    return {
        name: dict(info, app_count=0)
        for name, info in raw.items()
    }


hosts: dict = {}
apps: dict = {}
requirements: dict = {}
flows: dict = {}
dpids: dict = {}

def save():
    STATE_PATH.write_text(
        json.dumps(
            {"hosts": hosts, "apps": apps, "requirements": requirements,
             "flows": flows, "dpids": dpids},
            indent=2,
        )
    )

def load():
    global hosts, apps, requirements, flows, dpids
    if STATE_PATH.exists():
        data = json.loads(STATE_PATH.read_text())
        hosts = data.get("hosts", _init_hosts())
        apps = data.get("apps", {})
        requirements = data.get("requirements", {})
        flows = data.get("flows", {})
        dpids = {k: int(v) for k, v in data.get("dpids", {}).items()}
    else:
        hosts = _init_hosts()
        apps = {}
        requirements = {}
        flows = {}
        dpids = {}
