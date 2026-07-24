"""Helpers for freeform custom fields on lesson activities."""

from __future__ import annotations

import json


def parse_custom_fields(value: str | None) -> list[dict[str, str]]:
    """Parse a JSON list of {label, value} custom fields."""
    if not value or not str(value).strip():
        return []
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []

    fields: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()[:200]
        field_value = str(item.get("value") or "").strip()[:2000]
        if not label and not field_value:
            continue
        fields.append({"label": label, "value": field_value})
    return fields


def serialize_custom_fields(fields: list[dict] | None) -> str | None:
    """Serialize custom fields to a compact JSON string for storage."""
    cleaned = parse_custom_fields(json.dumps(fields or []))
    if not cleaned:
        return None
    return json.dumps(cleaned, ensure_ascii=False)
