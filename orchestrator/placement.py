MAX_APPS_PER_HOST = 2


def pick_host(hosts: dict) -> str | None:
    available = [h for h, info in hosts.items() if info["app_count"] < MAX_APPS_PER_HOST]
    if not available:
        return None
    return min(available, key=lambda h: hosts[h]["app_count"])
