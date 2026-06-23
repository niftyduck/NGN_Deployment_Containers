
""" Async HTTP wrapper around Ryu's REST API, to simplify repetitive
    instructions. It's used to control OpenFlow switches from the Ryu
    SDN controller.

    Since each function makes an HTTP call to Ryu's REST API at
    localhost:8080, they're all async (non-blocking)."""

import httpx

RYU_BASE = "http://localhost:8080"
TIMEOUT = 5.0

async def get_switches() -> list[int]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(f"{RYU_BASE}/stats/switches")
        r.raise_for_status()
        return r.json()


async def add_flow(dpid: int, match: dict, actions: list, priority: int = 100):
    body = {"dpid": dpid, "priority": priority, "match": match, "actions": actions}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{RYU_BASE}/stats/flowentry/add", json=body)
        r.raise_for_status()


async def delete_flow(dpid: int, match: dict, priority: int = 100):
    body = {"dpid": dpid, "priority": priority, "match": match}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # delete_strict matches exactly on priority + match fields
        r = await client.post(f"{RYU_BASE}/stats/flowentry/delete_strict", json=body)
        r.raise_for_status()


async def get_all_flows(dpid_list: list[int]) -> list:
    results = []
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for dpid in dpid_list:
            r = await client.get(f"{RYU_BASE}/stats/flow/{dpid}")
            r.raise_for_status()
            for flow in r.json().get(str(dpid), []):
                flow["dpid"] = dpid
                results.append(flow)
    return results
