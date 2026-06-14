import json
from pathlib import Path

HOST_MAP_PATH = Path(__file__).parent.parent / "kathara-labs" / "shared" / "host_map.json"
STATE_PATH = Path(__file__).parent / "state.json"


def _init_hosts() -> dict:
    with open(HOST_MAP_PATH) as f:
        raw = json.load(f)
    return {name: {**info, "app_count": 0} for name, info in raw.items()}


hosts: dict = {}
apps: dict = {}
requirements: dict = {}
flows: dict = {}
dpids: dict = {}  # switch_name → dpid (int)


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
