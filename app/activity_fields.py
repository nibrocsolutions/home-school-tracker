"""Helpers for freeform custom text blocks on lesson activities."""

from __future__ import annotations

import json


def parse_custom_fields(value: str | None) -> list[str]:
    """Parse stored custom text entries (JSON list of strings).

    Also accepts the legacy label/value object format and flattens it to text.
    """
    if not value or not str(value).strip():
        return []
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []

    texts: list[str] = []
    for item in data:
        text = ""
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            # Legacy {label, value} rows → plain text.
            label = str(item.get("label") or "").strip()
            field_value = str(item.get("value") or "").strip()
            if label and field_value:
                text = f"{label}: {field_value}"
            else:
                text = label or field_value
        if not text:
            continue
        texts.append(text[:2000])
    return texts


def serialize_custom_fields(fields: list | None) -> str | None:
    """Serialize custom text entries to a compact JSON string for storage."""
    cleaned = parse_custom_fields(json.dumps(fields or []))
    if not cleaned:
        return None
    return json.dumps(cleaned, ensure_ascii=False)
