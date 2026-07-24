from datetime import date

from app.models import ScheduleItemKind, SpecialActivityKind, WeeklyScheduleItem
from app.sample_plans import CLASSICAL_CONVERSATIONS_URL

WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
# Subjects schedule on school days only; weekend choices are omitted from subject editors.
SCHOOL_WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
SCHOOL_WEEKDAY_INDEXES = frozenset(range(5))

DEFAULT_SCHEDULE_ITEMS = [
    {
        "name": "Co-Op",
        "item_kind": ScheduleItemKind.special_activity,
        "special_type": SpecialActivityKind.co_op,
        "weekdays": "",
        "lesson_amount": 36,
        "description": "Community co-op classes with other homeschool families.",
        "include_numbering": False,
    },
    {
        "name": "Wild and Free Outing",
        "item_kind": ScheduleItemKind.special_activity,
        "special_type": SpecialActivityKind.wild_and_free,
        "weekdays": "",
        "lesson_amount": 36,
        "description": "Outdoor nature exploration and adventure learning.",
        "include_numbering": False,
    },
    {
        "name": "Classical Conversations Essentials",
        "item_kind": ScheduleItemKind.special_activity,
        "special_type": SpecialActivityKind.classical_conversations,
        "weekdays": "",
        "lesson_amount": 36,
        "description": "Essentials program — grammar, writing, and presentations.",
        "external_link": CLASSICAL_CONVERSATIONS_URL,
        "include_numbering": False,
    },
    {
        "name": "History",
        "item_kind": ScheduleItemKind.subject,
        "special_type": None,
        "weekdays": "",
        "lesson_amount": 72,
        "description": "Listen to the history audio lesson and share what you learned.",
        "include_numbering": True,
    },
    {
        "name": "Math",
        "item_kind": ScheduleItemKind.subject,
        "special_type": None,
        "weekdays": "",
        "lesson_amount": 120,
        "description": "Complete math workbook pages and practice problems.",
        "include_numbering": True,
    },
    {
        "name": "Language Arts",
        "item_kind": ScheduleItemKind.subject,
        "special_type": None,
        "weekdays": "",
        "lesson_amount": 120,
        "description": "Grammar, spelling, and creative writing.",
        "include_numbering": True,
    },
    {
        "name": "Science",
        "item_kind": ScheduleItemKind.subject,
        "special_type": None,
        "weekdays": "",
        "lesson_amount": 120,
        "description": "Hands-on experiments, observations, and science workbook lessons.",
        "include_numbering": True,
    },
]


def parse_weekdays(value: str) -> set[int]:
    if not value.strip():
        return set()
    return {int(part.strip()) for part in value.split(",") if part.strip().isdigit()}


def format_weekdays(value: str) -> str:
    days = sorted(parse_weekdays(value))
    return ", ".join(WEEKDAY_LABELS[d] for d in days if 0 <= d <= 6)


def normalize_school_weekdays(value: str) -> str:
    """Keep Mon–Fri only, preserving ascending order for subject schedules."""
    days = sorted(d for d in parse_weekdays(value) if d in SCHOOL_WEEKDAY_INDEXES)
    return ",".join(str(day) for day in days)


def weekday_index(plan_date: date) -> int:
    return plan_date.weekday()


def schedule_items_for_date(
    items: list[WeeklyScheduleItem], plan_date: date
) -> list[WeeklyScheduleItem]:
    day_idx = weekday_index(plan_date)
    return [item for item in items if day_idx in parse_weekdays(item.weekdays)]


LESSON_NUMBERED_SUBJECTS = frozenset({"math", "language arts", "history", "science"})


def default_include_numbering(name: str, item_kind: ScheduleItemKind | str | None = None) -> bool:
    """Return True when a new subject should default to lesson numbering."""
    kind_value = item_kind.value if isinstance(item_kind, ScheduleItemKind) else item_kind
    if kind_value and kind_value != ScheduleItemKind.subject.value:
        return False
    return name.strip().lower() in LESSON_NUMBERED_SUBJECTS


def subject_includes_numbering(item: WeeklyScheduleItem) -> bool:
    return bool(getattr(item, "include_numbering", False))


def schedule_item_base_title(item: WeeklyScheduleItem) -> str:
    if (
        item.item_kind == ScheduleItemKind.subject
        and item.name.lower() == "history"
        and not subject_includes_numbering(item)
    ):
        return f"History: {item.name}"
    return item.name


def schedule_item_to_activity(
    item: WeeklyScheduleItem, *, lesson_number: int | None = None
) -> dict:
    from app.models import ActivityType

    if item.item_kind == ScheduleItemKind.subject and item.name.lower() == "history":
        activity_type = ActivityType.history
    elif item.item_kind == ScheduleItemKind.special_activity:
        activity_type = ActivityType.special
    elif item.item_kind == ScheduleItemKind.subject:
        activity_type = ActivityType.subject
    else:
        activity_type = ActivityType.regular

    title = schedule_item_base_title(item)
    if (
        lesson_number is not None
        and item.item_kind == ScheduleItemKind.subject
        and subject_includes_numbering(item)
    ):
        title = f"{item.name} - Lesson {lesson_number}"

    return {
        "title": title,
        "description": item.description or "",
        "activity_type": activity_type.value,
        "teacher_notes": "",
        "external_link": (item.external_link or getattr(item, "audio_url", None) or "").strip(),
    }


def activity_matches_schedule_item(activity_title: str, item: WeeklyScheduleItem) -> bool:
    """Return True if an activity title was generated from this schedule item."""
    base = schedule_item_base_title(item)
    if activity_title == base or activity_title == item.name:
        return True
    # Legacy History titles used "History: History" even when numbering is now on.
    if item.item_kind == ScheduleItemKind.subject and item.name.lower() == "history":
        if activity_title == f"History: {item.name}":
            return True
    prefix = f"{item.name} - Lesson "
    if activity_title.startswith(prefix):
        suffix = activity_title[len(prefix) :]
        return suffix.isdigit()
    return False

