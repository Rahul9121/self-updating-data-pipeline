"""Offline tests using saved fixtures only (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.ingest import load_fixture
from pipeline.load import connect, event_count, fetch_all_events, upsert_events
from pipeline.run import run_pipeline
from pipeline.validate import validate_and_normalize

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def state_env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    site = tmp_path / "site"
    state.mkdir()
    site.mkdir()
    monkeypatch.setenv("PIPELINE_STATE_DIR", str(state))
    monkeypatch.setenv("PIPELINE_SITE_DIR", str(site))
    # reload path constants bound at import time
    import pipeline.build_site as build_site
    import pipeline.config as cfg
    import pipeline.run as run

    cfg.STATE_DIR = state
    cfg.DATA_DIR = state
    cfg.SITE_DIR = site
    cfg.DB_PATH = state / "earthquakes.sqlite"
    cfg.EVENTS_JSON = state / "events.json"
    cfg.EVENTS_PARQUET = state / "events.parquet"
    cfg.RUNS_JSON = state / "runs.json"
    cfg.META_JSON = state / "meta.json"
    cfg.REJECTED_JSON = state / "rejected_latest.json"
    cfg.BOOTSTRAP_MARKER = state / ".bootstrapped"

    run.DATA_DIR = cfg.DATA_DIR
    run.DB_PATH = cfg.DB_PATH
    run.EVENTS_JSON = cfg.EVENTS_JSON
    run.EVENTS_PARQUET = cfg.EVENTS_PARQUET
    run.RUNS_JSON = cfg.RUNS_JSON
    run.META_JSON = cfg.META_JSON
    run.REJECTED_JSON = cfg.REJECTED_JSON
    run.SITE_DIR = cfg.SITE_DIR
    run.BOOTSTRAP_MARKER = cfg.BOOTSTRAP_MARKER

    build_site.EVENTS_JSON = cfg.EVENTS_JSON
    build_site.EVENTS_PARQUET = cfg.EVENTS_PARQUET
    build_site.RUNS_JSON = cfg.RUNS_JSON
    build_site.META_JSON = cfg.META_JSON
    build_site.REJECTED_JSON = cfg.REJECTED_JSON
    build_site.SITE_DIR = cfg.SITE_DIR

    return state, site


def test_valid_feed_parses():
    payload = load_fixture(FIXTURES / "valid_feed.json")
    rows, rejected, errors = validate_and_normalize(payload)
    assert errors == []
    assert len(rows) == 3
    assert rejected == []
    assert rows[0]["event_id"] == "us1000a"


def test_malformed_records_rejected_with_reasons():
    payload = load_fixture(FIXTURES / "malformed_feed.json")
    rows, rejected, errors = validate_and_normalize(payload)
    assert errors == []
    assert len(rows) == 3
    assert len(rejected) >= 2
    reasons = " ".join(r["reason"] for r in rejected)
    assert "mag" in reasons.lower() or "null" in reasons.lower() or "coordinates" in reasons.lower()


def test_schema_change_fails_feed_validation():
    payload = load_fixture(FIXTURES / "schema_change.json")
    rows, rejected, errors = validate_and_normalize(payload)
    assert rows == []
    assert errors


def test_duplicate_and_updated_upsert(tmp_path):
    db = tmp_path / "t.sqlite"
    conn = connect(db)
    payload = load_fixture(FIXTURES / "valid_feed.json")
    rows, _, _ = validate_and_normalize(payload)
    c1 = upsert_events(conn, rows, "run1")
    assert c1 == {"new": 3, "updated": 0, "unchanged": 0}
    c2 = upsert_events(conn, rows, "run2")
    assert c2 == {"new": 0, "updated": 0, "unchanged": 3}
    updated_payload = load_fixture(FIXTURES / "updated_feed.json")
    rows2, _, _ = validate_and_normalize(updated_payload)
    c3 = upsert_events(conn, rows2, "run3")
    assert c3["new"] == 1
    assert c3["updated"] == 1
    assert c3["unchanged"] == 2
    events = {e["event_id"]: e for e in fetch_all_events(conn)}
    assert events["us1000a"]["magnitude"] == 4.8
    assert event_count(conn) == 4
    conn.close()


def test_idempotent_pipeline_rerun(state_env):
    state, site = state_env
    r1 = run_pipeline(fixture=FIXTURES / "valid_feed.json", build=True)
    assert r1["status"] == "success"
    assert r1["new"] == 3
    r2 = run_pipeline(fixture=FIXTURES / "valid_feed.json", build=True)
    assert r2["status"] == "success"
    assert r2["new"] == 0
    assert r2["unchanged"] == 3
    assert (site / "index.html").exists()
    meta = json.loads((state / "meta.json").read_text(encoding="utf-8"))
    assert meta["total_events"] == 3


def test_failed_run_keeps_last_good_events(state_env):
    state, site = state_env
    ok = run_pipeline(fixture=FIXTURES / "valid_feed.json", build=True)
    assert ok["status"] == "success"
    events_before = (state / "events.json").read_text(encoding="utf-8")
    index_before = (site / "index.html").read_text(encoding="utf-8")
    bad = run_pipeline(fixture=FIXTURES / "schema_change.json", build=True)
    assert bad["status"] == "failed"
    assert (state / "events.json").read_text(encoding="utf-8") == events_before
    assert (site / "index.html").read_text(encoding="utf-8") == index_before
