"""Export analytical snapshots for the static dashboard."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.config import STALE_HOURS


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")


def export_events_json(path: Path, events: list[dict[str, Any]]) -> None:
    _write_json(path, {"generated_at": _now(), "count": len(events), "events": events})


def export_events_parquet(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not events:
        table = pa.table(
            {
                "event_id": pa.array([], type=pa.string()),
                "magnitude": pa.array([], type=pa.float64()),
                "place": pa.array([], type=pa.string()),
                "event_time": pa.array([], type=pa.string()),
                "longitude": pa.array([], type=pa.float64()),
                "latitude": pa.array([], type=pa.float64()),
            }
        )
    else:
        table = pa.Table.from_pylist(events)
    pq.write_table(table, path)


def export_runs_json(path: Path, runs: list[dict[str, Any]]) -> None:
    _write_json(path, {"generated_at": _now(), "runs": runs})


def export_rejected_json(path: Path, rejected: list[dict[str, Any]]) -> None:
    _write_json(path, {"generated_at": _now(), "rejected": rejected})


def build_meta(
    *,
    events: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    rejected_count: int,
    last_run: dict[str, Any] | None,
) -> dict[str, Any]:
    last_success = next((r for r in runs if r.get("status") == "success"), None)
    last_success_at = last_success["finished_at"] if last_success else None
    stale = True
    age_hours = None
    if last_success_at:
        try:
            ts = datetime.strptime(last_success_at, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
            stale = age_hours > STALE_HOURS
        except ValueError:
            stale = True

    by_day: Counter[str] = Counter()
    mag_buckets = {"<2": 0, "2-3": 0, "3-4": 0, "4-5": 0, "5+": 0}
    for ev in events:
        et = ev.get("event_time") or ""
        day = et[:10] if len(et) >= 10 else "unknown"
        by_day[day] += 1
        mag = ev.get("magnitude")
        if mag is None:
            continue
        if mag < 2:
            mag_buckets["<2"] += 1
        elif mag < 3:
            mag_buckets["2-3"] += 1
        elif mag < 4:
            mag_buckets["3-4"] += 1
        elif mag < 5:
            mag_buckets["4-5"] += 1
        else:
            mag_buckets["5+"] += 1

    days_sorted = sorted(by_day.items())
    return {
        "generated_at": _now(),
        "total_events": len(events),
        "rejected_last_run": rejected_count,
        "last_success_at": last_success_at,
        "last_run": last_run,
        "stale": stale,
        "stale_hours_threshold": STALE_HOURS,
        "data_age_hours": round(age_hours, 2) if age_hours is not None else None,
        "events_per_day": [{"date": d, "count": c} for d, c in days_sorted],
        "magnitude_distribution": [{"bucket": k, "count": v} for k, v in mag_buckets.items()],
        "quality": {
            "events_with_coords": sum(
                1 for e in events if e.get("latitude") is not None and e.get("longitude") is not None
            ),
            "events_with_magnitude": sum(1 for e in events if e.get("magnitude") is not None),
            "max_magnitude": max((e["magnitude"] for e in events), default=None),
            "min_magnitude": min((e["magnitude"] for e in events), default=None),
        },
        "source": {
            "name": "USGS Earthquake Hazards Program",
            "feed": "all_week GeoJSON summary",
            "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_week.geojson",
            "credit": "Earthquake data provided by the U.S. Geological Survey (USGS).",
        },
        "disclaimer": (
            "Portfolio demo only. Not an alerting service. Do not rely on this page "
            "for safety or emergency decisions."
        ),
    }


def export_meta_json(path: Path, meta: dict[str, Any]) -> None:
    _write_json(path, meta)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
