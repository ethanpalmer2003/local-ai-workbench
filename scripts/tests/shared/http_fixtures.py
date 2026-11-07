"""Canned HTTP responses for requests/urllib callers; never perform network I/O."""

import json
from collections.abc import Mapping, Sequence
from email.message import Message
from typing import Any
from unittest.mock import MagicMock


def http_response(
    body: bytes = b"",
    *,
    status: int = 200,
    headers: Mapping[str, str] | None = None,
    content_type: str = "application/octet-stream",
    url: str = "https://example.test/asset",
    chunks: Sequence[bytes] | None = None,
) -> MagicMock:
    response = MagicMock(
        spec=[
            "__enter__",
            "__exit__",
            "read",
            "close",
            "iter_content",
            "raise_for_status",
            "json",
            "headers",
            "content",
            "status",
            "status_code",
            "code",
            "url",
        ]
    )
    response.status = response.status_code = response.code = status
    response.url, response.content = url, body
    response.headers = Message()
    for key, value in {"Content-Type": content_type, **(headers or {})}.items():
        response.headers[key] = value
    response.read.return_value = body
    response.iter_content.return_value = list(chunks) if chunks is not None else [body]
    response.json.side_effect = lambda: json.loads(body)
    response.__enter__.return_value = response

    def finish(*_):
        response.close()
        return False

    response.__exit__.side_effect = finish

    def check_status():
        if status >= 400:
            from requests import HTTPError

            raise HTTPError(f"Fixture HTTP {status}", response=response)

    response.raise_for_status.side_effect = check_status
    return response


def json_response(payload: Any, *, status: int = 200) -> MagicMock:
    return http_response(json.dumps(payload).encode(), status=status, content_type="application/json")
