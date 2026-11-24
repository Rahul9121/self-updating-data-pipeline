"""Idempotent SQLite store with upsert-by-id and updated time."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    magnitude REAL NOT NULL,
    place TEXT,
    event_time_ms INTEGER,
    event_time TEXT,
    updated_ms INTEGER NOT NULL,
    updated_time TEXT,
    longitude REAL,
    latitude REAL,
    depth_km REAL,
    mag_type TEXT,
    event_type TEXT,
    status TEXT,
    tsunami INTEGER,
    significance INTEGER,
    url TEXT,
    title TEXT,
    net TEXT,
    first_seen_run_id TEXT,
    last_seen_run_id TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    fetched INTEGER DEFAULT 0,
    new_count INTEGER DEFAULT 0,
    updated_count INTEGER DEFAULT 0,
    unchanged_count INTEGER DEFAULT 0,
    rejected_count INTEGER DEFAULT 0,
    duration_ms INTEGER,
    message TEXT,
    is_bootstrap INTEGER DEFAULT 0
);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    return conn


def upsert_events(
    conn: sqlite3.Connection,
    rows: list[dict[str, Any]],
    run_id: str,
) -> dict[str, int]:
    """
    Upsert by event_id.
    - insert if missing -> new
    - replace if incoming updated_ms > stored -> updated
    - else unchanged
    """
    new_count = updated_count = unchanged_count = 0
    select_sql = "SELECT updated_ms FROM events WHERE event_id = ?"
    insert_sql = """
        INSERT INTO events (
            event_id, magnitude, place, event_time_ms, event_time,
            updated_ms, updated_time, longitude, latitude, depth_km,
            mag_type, event_type, status, tsunami, significance,
            url, title, net, first_seen_run_id, last_seen_run_id
        ) VALUES (
            :event_id, :magnitude, :place, :event_time_ms, :event_time,
            :updated_ms, :updated_time, :longitude, :latitude, :depth_km,
            :mag_type, :event_type, :status, :tsunami, :significance,
            :url, :title, :net, :first_seen_run_id, :last_seen_run_id
        )
    """
    update_sql = """
        UPDATE events SET
            magnitude = :magnitude,
            place = :place,
            event_time_ms = :event_time_ms,
            event_time = :event_time,
            updated_ms = :updated_ms,
            updated_time = :updated_time,
            longitude = :longitude,
            latitude = :latitude,
            depth_km = :depth_km,
            mag_type = :mag_type,
            event_type = :event_type,
            status = :status,
            tsunami = :tsunami,
            significance = :significance,
            url = :url,
            title = :title,
            net = :net,
            last_seen_run_id = :last_seen_run_id
        WHERE event_id = :event_id
    """
    touch_sql = "UPDATE events SET last_seen_run_id = ? WHERE event_id = ?"

    for row in rows:
        payload = dict(row)
        payload["first_seen_run_id"] = run_id
        payload["last_seen_run_id"] = run_id
        existing = conn.execute(select_sql, (row["event_id"],)).fetchone()
        if existing is None:
            conn.execute(insert_sql, payload)
            new_count += 1
        elif int(row["updated_ms"]) > int(existing["updated_ms"]):
            conn.execute(update_sql, payload)
            updated_count += 1
        else:
            conn.execute(touch_sql, (run_id, row["event_id"]))
            unchanged_count += 1

    conn.commit()
    return {
        "new": new_count,
        "updated": updated_count,
        "unchanged": unchanged_count,
    }


def record_run(conn: sqlite3.Connection, run: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO runs (
            run_id, started_at, finished_at, status, fetched,
            new_count, updated_count, unchanged_count, rejected_count,
            duration_ms, message, is_bootstrap
        ) VALUES (
            :run_id, :started_at, :finished_at, :status, :fetched,
            :new_count, :updated_count, :unchanged_count, :rejected_count,
            :duration_ms, :message, :is_bootstrap
        )
        """,
        run,
    )
    conn.commit()


def fetch_all_events(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT event_id, magnitude, place, event_time_ms, event_time,
               updated_ms, updated_time, longitude, latitude, depth_km,
               mag_type, event_type, status, tsunami, significance,
               url, title, net
        FROM events
        ORDER BY event_time_ms DESC
        """
    )
    return [dict(row) for row in cur.fetchall()]


def fetch_runs(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT run_id, started_at, finished_at, status, fetched,
               new_count, updated_count, unchanged_count, rejected_count,
               duration_ms, message, is_bootstrap
        FROM runs
        ORDER BY started_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [dict(row) for row in cur.fetchall()]


def event_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()
    return int(row["c"])
