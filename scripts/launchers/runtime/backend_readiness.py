"""Native readiness routes shared by launchers, proxies and benchmark clients."""

ROUTES = {
    "llamacpp": "/health",
    "audiocpp": "/health",
    "sdcpp": "/v1/models",
    "koboldcpp": "/api/v1/model",
    "strata": "/v1/models",
}


def ready_url(backend: str, port: int, host: str = "127.0.0.1") -> str:
    return f"http://{host}:{port}{ROUTES[backend]}"
