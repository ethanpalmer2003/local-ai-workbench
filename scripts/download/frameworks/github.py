"""Single GitHub API entry point: one token, one header set, one JSON helper."""

import os

import requests

# - importing the config loads scripts/.env before the token is read
from scripts.config import project_config  # noqa: F401

API = "https://api.github.com"
# - GITHUB_TOKEN is optional; it only lifts the anonymous 60 requests/hour API limit
TOKEN = os.environ.get("GITHUB_TOKEN")
HEADERS = {"User-Agent": "update-frameworks"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

RATE_LIMIT_HINT = "GitHub API rate limit exceeded; set GITHUB_TOKEN in scripts/.env to raise it"


def get_json(url: str, params: dict[str, str] | None = None, timeout: int = 30):  # noqa: ANN201
    """GET an API URL and decode JSON, naming the rate limit when GitHub refuses for that reason."""
    response = requests.get(url, headers=HEADERS, params=params, timeout=timeout)
    if response.status_code == 403 and "rate limit" in response.text.lower():
        raise requests.HTTPError(RATE_LIMIT_HINT, response=response)
    response.raise_for_status()
    return response.json()
