"""Fetch the USGS GeoJSON feed once per run with retries and timeout."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

from pipeline.config import (
    FEED_URL,
    REQUEST_RETRIES,
    REQUEST_TIMEOUT_SEC,
    RETRY_BACKOFF_SEC,
    USER_AGENT,
)


class IngestError(Exception):
    """Raised when the feed cannot be fetched after retries."""


def fetch_feed(
    url: str = FEED_URL,
    *,
    timeout: float = REQUEST_TIMEOUT_SEC,
    retries: int = REQUEST_RETRIES,
    backoff: float = RETRY_BACKOFF_SEC,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """GET the feed. One logical request per run; retries only on failure."""
    own_session = session is None
    sess = session or requests.Session()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    last_error: Exception | None = None
    try:
        for attempt in range(1, retries + 1):
            try:
                resp = sess.get(url, headers=headers, timeout=timeout)
                resp.raise_for_status()
                payload = resp.json()
                if not isinstance(payload, dict):
                    raise IngestError("Feed root is not a JSON object")
                return payload
            except (requests.RequestException, ValueError, IngestError) as exc:
                last_error = exc
                if attempt < retries:
                    time.sleep(backoff * attempt)
        raise IngestError(f"Failed to fetch feed after {retries} attempts: {last_error}")
    finally:
        if own_session:
            sess.close()


def load_fixture(path: Path | str) -> dict[str, Any]:
    """Load a saved GeoJSON fixture from disk (tests / offline)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise IngestError("Fixture root is not a JSON object")
    return data
