from datetime import date

from app.models import ScheduleItemKind, SpecialActivityKind, WeeklyScheduleItem
from app.sample_plans import CLASSICAL_CONVERSATIONS_URL, HISTORY_AUDIO_URL

WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

DEFAULT_SCHEDULE_ITEMS = [
    {
        "name": "Co-Op",
        "item_kind": ScheduleItemKind.special_activity,
        "special_type": SpecialActivityKind.co_op,
        "weekdays": "0,2",
        "description": "Community co-op classes with other homeschool families.",
    },
    {
        "name": "Wild and Free Outing",
        "item_kind": ScheduleItemKind.special_activity,
        "special_type": SpecialActivityKind.wild_and_free,
        "weekdays": "4",
        "description": "Outdoor nature exploration and adventure learning.",
    },
    {
        "name": "Classical Conversations Essentials",
        "item_kind": ScheduleItemKind.special_activity,
        "special_type": SpecialActivityKind.classical_conversations,
        "weekdays": "0,2",
        "description": "Essentials program — grammar, writing, and presentations.",
        "external_link": CLASSICAL_CONVERSATIONS_URL,
    },
    {
        "name": "History",
        "item_kind": ScheduleItemKind.subject,
        "special_type": None,
        "weekdays": "0,2",
        "description": "Listen to the history audio lesson and share what you learned.",
        "audio_url": HISTORY_AUDIO_URL,
    },
    {
        "name": "Math",
        "item_kind": ScheduleItemKind.subject,
        "special_type": None,
        "weekdays": "1,3",
        "description": "Complete math workbook pages and practice problems.",
    },
    {
        "name": "Language Arts",
        "item_kind": ScheduleItemKind.subject,
        "special_type": None,
        "weekdays": "1,3,4",
        "description": "Grammar, spelling, and creative writing.",
    },
]


def parse_weekdays(value: str) -> set[int]:
    if not value.strip():
        return set()
    return {int(part.strip()) for part in value.split(",") if part.strip().isdigit()}


def format_weekdays(value: str) -> str:
    days = sorted(parse_weekdays(value))
    return ", ".join(WEEKDAY_LABELS[d] for d in days if 0 <= d <= 6)


def weekday_index(plan_date: date) -> int:
    return plan_date.weekday()


def schedule_items_for_date(
    items: list[WeeklyScheduleItem], plan_date: date
) -> list[WeeklyScheduleItem]:
    day_idx = weekday_index(plan_date)
    return [item for item in items if day_idx in parse_weekdays(item.weekdays)]


LESSON_NUMBERED_SUBJECTS = frozenset({"math", "language arts"})


def schedule_item_base_title(item: WeeklyScheduleItem) -> str:
    if item.item_kind == ScheduleItemKind.subject and item.name.lower() == "history":
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
        and item.name.lower() in LESSON_NUMBERED_SUBJECTS
    ):
        title = f"{item.name} - Lesson {lesson_number}"

    return {
        "title": title,
        "description": item.description or "",
        "activity_type": activity_type.value,
        "audio_url": item.audio_url or "",
        "external_link": item.external_link or "",
    }


def activity_matches_schedule_item(activity_title: str, item: WeeklyScheduleItem) -> bool:
    """Return True if an activity title was generated from this schedule item."""
    base = schedule_item_base_title(item)
    if activity_title == base or activity_title == item.name:
        return True
    prefix = f"{item.name} - Lesson "
    if activity_title.startswith(prefix):
        suffix = activity_title[len(prefix) :]
        return suffix.isdigit()
    return False

