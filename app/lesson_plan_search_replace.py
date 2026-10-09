"""Search and replace text across a teacher's lesson plans and activities."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.activity_fields import parse_custom_fields, serialize_custom_fields
from app.models import LessonPlan

PLAN_TITLE_MAX = 200
ACTIVITY_TITLE_MAX = 200


@dataclass(frozen=True)
class SearchReplaceResult:
    replacements: int
    plans_updated: int
    activities_updated: int


def _replace_in_text(
    value: str | None,
    find: str,
    replace: str,
    *,
    case_sensitive: bool,
    max_length: int | None = None,
) -> tuple[str | None, int]:
    if value is None or find == "":
        return value, 0

    if case_sensitive:
        count = value.count(find)
        if count == 0:
            return value, 0
        updated = value.replace(find, replace)
    else:
        pattern = re.compile(re.escape(find), re.IGNORECASE)
        count = len(pattern.findall(value))
        if count == 0:
            return value, 0
        updated = pattern.sub(replace, value)

    if max_length is not None and len(updated) > max_length:
        updated = updated[:max_length]
    return updated, count


def _replace_in_custom_fields(
    value: str | None,
    find: str,
    replace: str,
    *,
    case_sensitive: bool,
) -> tuple[str | None, int]:
    fields = parse_custom_fields(value)
    if not fields:
        return value, 0

    total = 0
    updated_fields: list[str] = []
    for field in fields:
        new_field, count = _replace_in_text(
            field, find, replace, case_sensitive=case_sensitive
        )
        total += count
        updated_fields.append(new_field or "")

    if total == 0:
        return value, 0
    return serialize_custom_fields(updated_fields), total


def apply_search_replace(
    plans: list[LessonPlan],
    find: str,
    replace: str,
    *,
    case_sensitive: bool = True,
) -> SearchReplaceResult:
    """Apply find/replace across plan and activity text fields. Mutates in place.

    Covers lesson plan title/description and activity title, description,
    teacher notes, and custom text fields. Does not modify media URLs or
    external links.
    """
    find = find or ""
    replace = replace if replace is not None else ""
    if not find:
        return SearchReplaceResult(0, 0, 0)

    total_replacements = 0
    plans_updated = 0
    activities_updated = 0

    for plan in plans:
        plan_touch = False

        new_title, count = _replace_in_text(
            plan.title,
            find,
            replace,
            case_sensitive=case_sensitive,
            max_length=PLAN_TITLE_MAX,
        )
        if count:
            plan.title = new_title or ""
            total_replacements += count
            plan_touch = True

        new_description, count = _replace_in_text(
            plan.description, find, replace, case_sensitive=case_sensitive
        )
        if count:
            plan.description = new_description
            total_replacements += count
            plan_touch = True

        for activity in plan.activities:
            activity_touch = False

            new_title, count = _replace_in_text(
                activity.title,
                find,
                replace,
                case_sensitive=case_sensitive,
                max_length=ACTIVITY_TITLE_MAX,
            )
            if count:
                activity.title = new_title or ""
                total_replacements += count
                activity_touch = True

            new_description, count = _replace_in_text(
                activity.description, find, replace, case_sensitive=case_sensitive
            )
            if count:
                activity.description = new_description
                total_replacements += count
                activity_touch = True

            new_notes, count = _replace_in_text(
                activity.teacher_notes, find, replace, case_sensitive=case_sensitive
            )
            if count:
                activity.teacher_notes = new_notes
                total_replacements += count
                activity_touch = True

            new_custom, count = _replace_in_custom_fields(
                activity.custom_fields,
                find,
                replace,
                case_sensitive=case_sensitive,
            )
            if count:
                activity.custom_fields = new_custom
                total_replacements += count
                activity_touch = True

            if activity_touch:
                activities_updated += 1
                plan_touch = True

        if plan_touch:
            plans_updated += 1

    return SearchReplaceResult(
        replacements=total_replacements,
        plans_updated=plans_updated,
        activities_updated=activities_updated,
    )
