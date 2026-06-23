
""" This function just picks the available hosts in the network
    and picks the best one (the one with less apps running)."""

MAX_APPS_PER_HOST = 2

def pick_host(hosts: dict) -> str | None:
    available = []

    for host_name, host_info in hosts.items():
        if host_info["app_count"] < MAX_APPS_PER_HOST:
            available.append(host_name)

    if len(available) == 0:
        return None

    best_host = available[0]

    for host_name in available:
        if hosts[host_name]["app_count"] < hosts[best_host]["app_count"]:
            best_host = host_name

    return best_host