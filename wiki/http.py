"""Minimal JSON-over-HTTP shared by the model clients.

Stdlib only, matching `function_summaries.py`: the visualizer's serving path
should not grow a hard HTTP dependency for what is three POSTs.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

TransportError = (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError)


def api_root(url: str | None) -> str:
    """Normalise a base URL so `/v1/...` can always be appended.

    Endpoints get written down both ways — `http://host:8000` and
    `216.193.128.133:42497/v1` — and a missing scheme or a doubled `/v1/v1`
    fails with a connection error that looks like the server being down.
    """
    text = (url or "").strip().rstrip("/")
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        text = f"http://{text}"
    if text.endswith("/v1"):
        text = text[: -len("/v1")]
    return text.rstrip("/")


def post_json(url: str, payload: dict, api_key: str = "EMPTY", timeout: float = 120.0) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key or 'EMPTY'}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str, timeout: float = 10.0) -> Any:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))
