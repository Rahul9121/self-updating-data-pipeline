"""Schema validation and rejected-record handling."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from jsonschema import Draft202012Validator

FEATURE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["type", "id", "properties", "geometry"],
    "properties": {
        "type": {"const": "Feature"},
        "id": {"type": "string", "minLength": 1},
        "properties": {
            "type": "object",
            "required": ["mag", "place", "time", "updated", "type", "title", "status"],
            "properties": {
                "mag": {"type": ["number", "null"]},
                "place": {"type": ["string", "null"]},
                "time": {"type": "integer"},
                "updated": {"type": "integer"},
                "tz": {"type": ["integer", "null"]},
                "url": {"type": ["string", "null"]},
                "detail": {"type": ["string", "null"]},
                "felt": {"type": ["integer", "null"]},
                "cdi": {"type": ["number", "null"]},
                "mmi": {"type": ["number", "null"]},
                "alert": {"type": ["string", "null"]},
                "status": {"type": "string"},
                "tsunami": {"type": ["integer", "null"]},
                "sig": {"type": ["integer", "null"]},
                "net": {"type": ["string", "null"]},
                "code": {"type": ["string", "null"]},
                "ids": {"type": ["string", "null"]},
                "sources": {"type": ["string", "null"]},
                "types": {"type": ["string", "null"]},
                "nst": {"type": ["integer", "null"]},
                "dmin": {"type": ["number", "null"]},
                "rms": {"type": ["number", "null"]},
                "gap": {"type": ["number", "null"]},
                "magType": {"type": ["string", "null"]},
                "type": {"type": "string"},
                "title": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "geometry": {
            "type": ["object", "null"],
            "properties": {
                "type": {"type": "string"},
                "coordinates": {
                    "type": "array",
                    "minItems": 2,
                    "items": {"type": ["number", "null"]},
                },
            },
        },
    },
    "additionalProperties": True,
}

FEED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["type", "features"],
    "properties": {
        "type": {"const": "FeatureCollection"},
        "metadata": {"type": "object"},
        "features": {"type": "array"},
        "bbox": {"type": "array"},
    },
    "additionalProperties": True,
}

_feature_validator = Draft202012Validator(FEATURE_SCHEMA)
_feed_validator = Draft202012Validator(FEED_SCHEMA)


def _ms_to_iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_feed_envelope(payload: dict[str, Any]) -> list[str]:
    """Return feed-level errors (empty if ok)."""
    return [e.message for e in sorted(_feed_validator.iter_errors(payload), key=lambda x: x.path)]


def normalize_feature(feature: dict[str, Any]) -> dict[str, Any]:
    """Map a GeoJSON feature to a flat analytical row."""
    props = feature.get("properties") or {}
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates") if isinstance(geom, dict) else None
    lon = lat = depth = None
    if isinstance(coords, list) and len(coords) >= 2:
        lon = coords[0] if isinstance(coords[0], (int, float)) else None
        lat = coords[1] if isinstance(coords[1], (int, float)) else None
        if len(coords) >= 3 and isinstance(coords[2], (int, float)):
            depth = float(coords[2])
    event_id = str(feature.get("id") or props.get("code") or "")
    time_ms = props.get("time")
    updated_ms = props.get("updated")
    mag = props.get("mag")
    return {
        "event_id": event_id,
        "magnitude": float(mag) if isinstance(mag, (int, float)) else None,
        "place": props.get("place"),
        "event_time_ms": time_ms,
        "event_time": _ms_to_iso(time_ms if isinstance(time_ms, int) else None),
        "updated_ms": updated_ms,
        "updated_time": _ms_to_iso(updated_ms if isinstance(updated_ms, int) else None),
        "longitude": float(lon) if lon is not None else None,
        "latitude": float(lat) if lat is not None else None,
        "depth_km": depth,
        "mag_type": props.get("magType"),
        "event_type": props.get("type"),
        "status": props.get("status"),
        "tsunami": props.get("tsunami"),
        "significance": props.get("sig"),
        "url": props.get("url"),
        "title": props.get("title"),
        "net": props.get("net"),
    }


def validate_and_normalize(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """
    Validate feed and features.

    Returns (valid_rows, rejected, feed_errors).
    Rejected entries include event id (if any) and reason.
    """
    feed_errors = validate_feed_envelope(payload)
    if feed_errors:
        return [], [], feed_errors

    features = payload.get("features") or []
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for idx, feature in enumerate(features):
        if not isinstance(feature, dict):
            rejected.append({"index": idx, "event_id": None, "reason": "feature is not an object"})
            continue
        errors = sorted(_feature_validator.iter_errors(feature), key=lambda e: list(e.path))
        if errors:
            reason = "; ".join(err.message for err in errors[:3])
            rejected.append(
                {
                    "index": idx,
                    "event_id": feature.get("id"),
                    "reason": reason,
                }
            )
            continue
        row = normalize_feature(feature)
        if row["magnitude"] is None:
            rejected.append(
                {
                    "index": idx,
                    "event_id": row["event_id"],
                    "reason": "magnitude is null (excluded from analytical set)",
                }
            )
            continue
        if row["latitude"] is None or row["longitude"] is None:
            rejected.append(
                {
                    "index": idx,
                    "event_id": row["event_id"],
                    "reason": "missing coordinates",
                }
            )
            continue
        valid.append(row)

    return valid, rejected, []
