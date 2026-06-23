

""" Helper to let the orchestrator control devices inside Kathar by
    running 'kathara exec' command-line tool. """

import subprocess
from pathlib import Path

LAB_DIR = str(Path(__file__).parent.parent / "kathara-labs")

def _exec(device: str, cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["kathara", "exec", device, "--", "bash", "-c", cmd],
        capture_output=True,
        text=True,
        cwd=LAB_DIR,
    )


def get_dpid(switch_name: str) -> int:
    """Return the OpenFlow dpid (int) of an OVS bridge running in a Kathará container."""
    result = _exec(switch_name, f"ovs-vsctl get bridge {switch_name} datapath-id")
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to get dpid for {switch_name}: {result.stderr.strip()}"
        )

    # OVS prints the value quoted: "0000000000000001"
    raw = result.stdout.strip().strip('"')
    return int(raw, 16)


def start_app(host: str, app_type: str, env: dict) -> subprocess.CompletedProcess:
    env_str = " ".join(f'{k}="{v}"' for k, v in env.items())
    cmd = f"cd /shared/apps && {env_str} python3 {app_type}.py > /tmp/{app_type}.log 2>&1 &"
    return _exec(host, cmd)


def stop_app(host: str, app_type: str):
    _exec(host, f"pkill -f {app_type}.py || true")
