"""End-to-end pipeline: ingest -> validate -> load -> export -> site."""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.build_site import build_site
from pipeline.config import (
    BOOTSTRAP_MARKER,
    DATA_DIR,
    DB_PATH,
    EVENTS_JSON,
    EVENTS_PARQUET,
    META_JSON,
    REJECTED_JSON,
    RUNS_JSON,
    SITE_DIR,
)
from pipeline.export import (
    build_meta,
    export_events_json,
    export_events_parquet,
    export_meta_json,
    export_rejected_json,
    export_runs_json,
)
from pipeline.ingest import IngestError, fetch_feed, load_fixture
from pipeline.load import (
    connect,
    event_count,
    fetch_all_events,
    fetch_runs,
    record_run,
    upsert_events,
)
from pipeline.validate import validate_and_normalize


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_state_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def run_pipeline(
    *,
    fixture: Path | None = None,
    fail_site_on_error: bool = True,
    build: bool = True,
) -> dict[str, Any]:
    """
    Execute one pipeline run.

    On failure after load has not committed a success export, previous JSON
    snapshots and site files are left untouched when callers skip rebuild.
    """
    _ensure_state_dir()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    started = _now()
    t0 = time.perf_counter()
    is_bootstrap = not BOOTSTRAP_MARKER.exists() or not DB_PATH.exists()

    conn = connect(DB_PATH)
    result: dict[str, Any] = {
        "run_id": run_id,
        "status": "failed",
        "is_bootstrap": is_bootstrap,
    }

    try:
        if fixture is not None:
            payload = load_fixture(fixture)
        else:
            payload = fetch_feed()

        rows, rejected, feed_errors = validate_and_normalize(payload)
        if feed_errors:
            raise IngestError("Feed schema invalid: " + "; ".join(feed_errors))

        counts = upsert_events(conn, rows, run_id)
        events = fetch_all_events(conn)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        finished = _now()

        run_row = {
            "run_id": run_id,
            "started_at": started,
            "finished_at": finished,
            "status": "success",
            "fetched": len(rows) + len(rejected),
            "new_count": counts["new"],
            "updated_count": counts["updated"],
            "unchanged_count": counts["unchanged"],
            "rejected_count": len(rejected),
            "duration_ms": duration_ms,
            "message": "ok" if not is_bootstrap else "bootstrap",
            "is_bootstrap": 1 if is_bootstrap else 0,
        }
        record_run(conn, run_row)

        runs = fetch_runs(conn)
        export_events_json(EVENTS_JSON, events)
        export_events_parquet(EVENTS_PARQUET, events)
        export_runs_json(RUNS_JSON, runs)
        export_rejected_json(REJECTED_JSON, rejected)
        meta = build_meta(
            events=events,
            runs=runs,
            rejected_count=len(rejected),
            last_run=run_row,
        )
        export_meta_json(META_JSON, meta)

        if build:
            build_site(site_dir=SITE_DIR)

        BOOTSTRAP_MARKER.write_text(finished, encoding="utf-8")
        result.update(
            {
                "status": "success",
                "fetched": run_row["fetched"],
                "new": counts["new"],
                "updated": counts["updated"],
                "unchanged": counts["unchanged"],
                "rejected": len(rejected),
                "duration_ms": duration_ms,
                "total_events": event_count(conn),
            }
        )
        return result

    except Exception as exc:  # noqa: BLE001 - top-level run boundary
        duration_ms = int((time.perf_counter() - t0) * 1000)
        finished = _now()
        message = f"{type(exc).__name__}: {exc}"
        run_row = {
            "run_id": run_id,
            "started_at": started,
            "finished_at": finished,
            "status": "failed",
            "fetched": 0,
            "new_count": 0,
            "updated_count": 0,
            "unchanged_count": 0,
            "rejected_count": 0,
            "duration_ms": duration_ms,
            "message": message[:500],
            "is_bootstrap": 1 if is_bootstrap else 0,
        }
        try:
            record_run(conn, run_row)
            # Do not overwrite events/meta/site on failure. Only append run history
            # if we already have a prior successful export; otherwise write minimal runs.
            if EVENTS_JSON.exists() and META_JSON.exists():
                runs = fetch_runs(conn)
                export_runs_json(RUNS_JSON, runs)
                # refresh meta stale flag without replacing event snapshot
                events = fetch_all_events(conn) if DB_PATH.exists() else []
                prev_meta = {}
                try:
                    prev_meta = json.loads(META_JSON.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    prev_meta = {}
                meta = build_meta(
                    events=events,
                    runs=runs,
                    rejected_count=int(prev_meta.get("rejected_last_run") or 0),
                    last_run=run_row,
                )
                # keep last_success based on runs; rebuild site only if asked
                if not fail_site_on_error:
                    export_meta_json(META_JSON, meta)
                    build_site(site_dir=SITE_DIR)
            result.update({"status": "failed", "message": message, "duration_ms": duration_ms})
        except Exception:  # noqa: BLE001
            result["message"] = message + " | " + traceback.format_exc()[-300:]
        return result
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the USGS earthquake pipeline")
    parser.add_argument("--fixture", type=Path, default=None, help="Use a local GeoJSON fixture")
    parser.add_argument("--no-build", action="store_true", help="Skip static site build")
    parser.add_argument(
        "--update-site-on-failure",
        action="store_true",
        help="Rebuild site after failed run (still keeps last good events)",
    )
    args = parser.parse_args(argv)
    result = run_pipeline(
        fixture=args.fixture,
        fail_site_on_error=not args.update_site_on_failure,
        build=not args.no_build,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
