"""Runtime paths and constants."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = Path(os.environ.get("PIPELINE_STATE_DIR", ROOT / "state")).resolve()
DATA_DIR = STATE_DIR
SITE_DIR = Path(os.environ.get("PIPELINE_SITE_DIR", ROOT / "site" / "dist")).resolve()
FIXTURE_DIR = ROOT / "tests" / "fixtures"

FEED_URL = os.environ.get(
    "PIPELINE_FEED_URL",
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_week.geojson",
)
USER_AGENT = (
    "SelfUpdatingDataPipeline/1.0 "
    "(+https://github.com/Rahul9121/self-updating-data-pipeline; portfolio demo)"
)
REQUEST_TIMEOUT_SEC = float(os.environ.get("PIPELINE_TIMEOUT", "30"))
REQUEST_RETRIES = int(os.environ.get("PIPELINE_RETRIES", "3"))
RETRY_BACKOFF_SEC = float(os.environ.get("PIPELINE_RETRY_BACKOFF", "2"))

DB_PATH = DATA_DIR / "earthquakes.sqlite"
EVENTS_JSON = DATA_DIR / "events.json"
EVENTS_PARQUET = DATA_DIR / "events.parquet"
RUNS_JSON = DATA_DIR / "runs.json"
META_JSON = DATA_DIR / "meta.json"
REJECTED_JSON = DATA_DIR / "rejected_latest.json"

STALE_HOURS = 36
BOOTSTRAP_MARKER = DATA_DIR / ".bootstrapped"
