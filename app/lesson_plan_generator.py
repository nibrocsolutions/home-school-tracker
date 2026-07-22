from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from app.models import (
    Activity,
    ActivityCompletion,
    ActivityType,
    LessonPlan,
    SchoolDayType,
    SchoolDayYear,
    WeeklyScheduleItem,
)
from app.school_year_utils import _day_type_value, iter_dates_in_range
from app.weekly_schedule import (
    activity_matches_schedule_item,
    parse_weekdays,
    schedule_item_to_activity,
)


def distribute_lesson_dates(matching_days: list[date], lesson_amount: int) -> list[date]:
    """Fill consecutively from the start of matching days; stop when amount is reached."""
    if lesson_amount <= 0 or not matching_days:
        return []
    return matching_days[:lesson_amount]


def _is_actual_school_day_type(day_type: SchoolDayType | str | None) -> bool:
    return _day_type_value(day_type) == SchoolDayType.actual_school.value


def actual_school_days_in_year(school_year: SchoolDayYear) -> list[date]:
    """Return planned actual school days only (never weekends, days off, or holidays)."""
    planned_map = {day.day_date: day for day in school_year.planned_days}
    days: list[date] = []
    for day_date in iter_dates_in_range(school_year.start_date, school_year.end_date):
        planned = planned_map.get(day_date)
        if planned is None:
            continue
        if _is_actual_school_day_type(planned.day_type):
            days.append(day_date)
    return days


def matching_available_days(
    school_year: SchoolDayYear, weekdays: set[int]
) -> list[date]:
    """Actual school days that also match the subject's weekday picker."""
    if not weekdays:
        return []
    return [d for d in actual_school_days_in_year(school_year) if d.weekday() in weekdays]


def build_subject_assignments(
    school_year: SchoolDayYear,
    schedule_items: list[WeeklyScheduleItem],
) -> dict[date, list[dict]]:
    assignments: dict[date, list[dict]] = {}

    for item in schedule_items:
        lesson_amount = item.lesson_amount or 0
        if lesson_amount <= 0:
            continue
        weekdays = parse_weekdays(item.weekdays)
        if not weekdays:
            continue

        matching = matching_available_days(school_year, weekdays)
        selected_dates = distribute_lesson_dates(matching, lesson_amount)
        for lesson_number, day_date in enumerate(selected_dates, start=1):
            activity = schedule_item_to_activity(item, lesson_number=lesson_number)
            assignments.setdefault(day_date, []).append(activity)

    return assignments


def _activity_exists(plan: LessonPlan, title: str) -> bool:
    return any(activity.title == title for activity in plan.activities)


def _activity_is_completed(activity: Activity, student_id: int) -> bool:
    for completion in activity.completions:
        if completion.student_id == student_id and completion.completed:
            return True
    return False


def _clear_schedule_item_activities(
    db: Session,
    teacher_id: int,
    school_year: SchoolDayYear,
    schedule_items: list[WeeklyScheduleItem],
    *,
    preserve_completed: bool = False,
) -> dict[int, dict[int, list[dict | None]]]:
    """Remove previously auto-populated activities for the given subjects so they can be rebuilt.

    Returns preserved teacher-message payloads keyed by schedule item id then student id,
    in plan-date order for the activities being removed. Messages move with lessons when
    unfinished work is rescheduled.
    """
    preserved: dict[int, dict[int, list[dict | None]]] = {
        item.id: {} for item in schedule_items
    }
    if not schedule_items:
        return preserved

    plans = (
        db.query(LessonPlan)
        .options(
            joinedload(LessonPlan.activities).joinedload(Activity.completions),
        )
        .filter(
            LessonPlan.teacher_id == teacher_id,
            LessonPlan.plan_date >= school_year.start_date,
            LessonPlan.plan_date <= school_year.end_date,
        )
        .order_by(LessonPlan.plan_date, LessonPlan.id)
        .all()
    )

    # Collect removable activities in date order before deleting.
    pending_delete: list[tuple[WeeklyScheduleItem, LessonPlan, Activity]] = []
    empty_plans: list[LessonPlan] = []
    for plan in plans:
        remaining = []
        for activity in list(plan.activities):
            matched_item = next(
                (
                    item
                    for item in schedule_items
                    if activity_matches_schedule_item(activity.title, item)
                ),
                None,
            )
            if matched_item is not None and not (
                preserve_completed and _activity_is_completed(activity, plan.student_id)
            ):
                pending_delete.append((matched_item, plan, activity))
            else:
                remaining.append(activity)
        if not remaining:
            empty_plans.append(plan)

    pending_delete.sort(key=lambda row: (row[1].plan_date, row[1].id, row[2].sort_order, row[2].id))
    for item, plan, activity in pending_delete:
        student_bucket = preserved[item.id].setdefault(plan.student_id, [])
        completion = next(
            (
                entry
                for entry in activity.completions
                if entry.student_id == plan.student_id
            ),
            None,
        )
        if completion and completion.student_message and completion.student_message.strip():
            student_bucket.append(
                {
                    "student_message": completion.student_message,
                    "message_read_at": completion.message_read_at,
                }
            )
        else:
            student_bucket.append(None)
        db.delete(activity)

    db.flush()
    for plan in empty_plans:
        db.delete(plan)
    db.flush()
    db.expire_all()
    return preserved


def _restore_preserved_messages(
    db: Session,
    teacher_id: int,
    school_year: SchoolDayYear,
    schedule_items: list[WeeklyScheduleItem],
    preserved: dict[int, dict[int, list[dict | None]]],
) -> None:
    """Re-attach preserved student messages onto rebuilt unfinished activities by date order."""
    if not preserved:
        return

    plans = (
        db.query(LessonPlan)
        .options(
            joinedload(LessonPlan.activities).joinedload(Activity.completions),
        )
        .filter(
            LessonPlan.teacher_id == teacher_id,
            LessonPlan.plan_date >= school_year.start_date,
            LessonPlan.plan_date <= school_year.end_date,
        )
        .order_by(LessonPlan.plan_date, LessonPlan.id)
        .all()
    )

    for item in schedule_items:
        by_student = preserved.get(item.id) or {}
        for student_id, payloads in by_student.items():
            if not payloads:
                continue
            rebuilt: list[Activity] = []
            for plan in plans:
                if plan.student_id != student_id:
                    continue
                for activity in sorted(plan.activities, key=lambda a: (a.sort_order, a.id)):
                    if not activity_matches_schedule_item(activity.title, item):
                        continue
                    # Only unfinished rebuilt lessons receive shifted messages.
                    if _activity_is_completed(activity, student_id):
                        continue
                    rebuilt.append(activity)
            for activity, payload in zip(rebuilt, payloads):
                if not payload:
                    continue
                message = (payload.get("student_message") or "").strip()
                if not message:
                    continue
                completion = next(
                    (
                        entry
                        for entry in activity.completions
                        if entry.student_id == student_id
                    ),
                    None,
                )
                if completion is None:
                    completion = ActivityCompletion(
                        activity_id=activity.id,
                        student_id=student_id,
                        completed=False,
                        student_message=message,
                        message_read_at=payload.get("message_read_at"),
                    )
                    db.add(completion)
                else:
                    # Keep an existing message if somehow present; otherwise restore.
                    if not (completion.student_message and completion.student_message.strip()):
                        completion.student_message = message
                        completion.message_read_at = payload.get("message_read_at")
    db.flush()


def _auto_plan_title(plan_date: date) -> str:
    return plan_date.strftime("%A, %B %d, %Y")


def _merge_plan_into(db: Session, source: LessonPlan, target: LessonPlan) -> None:
    """Move activities from source into target, then delete source."""
    next_sort = max((activity.sort_order for activity in target.activities), default=0)
    for activity in list(source.activities):
        if _activity_exists(target, activity.title):
            db.delete(activity)
            continue
        next_sort += 1
        activity.lesson_plan_id = target.id
        activity.sort_order = next_sort
    db.flush()
    db.delete(source)


def snap_lesson_plans_to_actual_school_days(
    db: Session,
    teacher_id: int,
    school_year: SchoolDayYear,
) -> int:
    """Move any in-range lesson plans off weekends/days off onto planned actual school days."""
    actual_days = actual_school_days_in_year(school_year)
    if not actual_days:
        return 0
    actual_set = set(actual_days)

    plans = (
        db.query(LessonPlan)
        .options(joinedload(LessonPlan.activities))
        .filter(
            LessonPlan.teacher_id == teacher_id,
            LessonPlan.plan_date >= school_year.start_date,
            LessonPlan.plan_date <= school_year.end_date,
        )
        .order_by(LessonPlan.plan_date, LessonPlan.id)
        .all()
    )

    plans_by_key: dict[tuple[date, int], LessonPlan] = {
        (plan.plan_date, plan.student_id): plan for plan in plans
    }

    moved = 0
    for plan in list(plans):
        if plan.plan_date in actual_set:
            continue

        target = next((day for day in actual_days if day >= plan.plan_date), None)
        if target is None:
            target = next((day for day in reversed(actual_days) if day <= plan.plan_date), None)
        if target is None or target == plan.plan_date:
            continue

        existing = plans_by_key.get((target, plan.student_id))
        old_key = (plan.plan_date, plan.student_id)
        if existing is not None and existing.id != plan.id:
            _merge_plan_into(db, plan, existing)
            plans_by_key.pop(old_key, None)
        else:
            if plan.title == _auto_plan_title(plan.plan_date):
                plan.title = _auto_plan_title(target)
            plan.plan_date = target
            plans_by_key.pop(old_key, None)
            plans_by_key[(target, plan.student_id)] = plan
        moved += 1

    db.flush()
    return moved


def shift_lesson_plans_by_days(
    db: Session,
    teacher_id: int,
    old_start: date,
    old_end: date,
    day_delta: int,
    school_year: SchoolDayYear | None = None,
) -> int:
    """Move lesson plans within the previous school-year range by day_delta days.

    When school_year is provided (with updated dates and planned days), plans that
    land on weekends or days off are snapped onto the next planned actual school day.
    """
    if day_delta == 0:
        return 0

    delta = timedelta(days=day_delta)
    plans = (
        db.query(LessonPlan)
        .filter(
            LessonPlan.teacher_id == teacher_id,
            LessonPlan.plan_date >= old_start,
            LessonPlan.plan_date <= old_end,
        )
        .all()
    )

    shifted = 0
    for plan in plans:
        old_date = plan.plan_date
        new_date = old_date + delta
        if plan.title == _auto_plan_title(old_date):
            plan.title = _auto_plan_title(new_date)
        plan.plan_date = new_date
        shifted += 1

    db.flush()

    if school_year is not None:
        snap_lesson_plans_to_actual_school_days(db, teacher_id, school_year)

    return shifted


def _add_activity_to_plan(
    db: Session,
    plan: LessonPlan,
    activity_data: dict,
    *,
    sort_order: int,
) -> None:
    try:
        activity_type = ActivityType(activity_data["activity_type"])
    except ValueError:
        activity_type = ActivityType.regular
    db.add(
        Activity(
            lesson_plan_id=plan.id,
            title=activity_data["title"],
            description=activity_data["description"] or None,
            sort_order=sort_order,
            activity_type=activity_type,
            teacher_notes=activity_data.get("teacher_notes") or None,
            external_link=activity_data["external_link"] or None,
        )
    )


def _get_or_create_plan(
    db: Session,
    plans_by_date_student: dict[tuple[date, int], LessonPlan],
    *,
    teacher_id: int,
    plan_date: date,
    student_id: int,
) -> LessonPlan:
    plan = plans_by_date_student.get((plan_date, student_id))
    if plan is not None:
        return plan
    plan = LessonPlan(
        title=_auto_plan_title(plan_date),
        description=None,
        plan_date=plan_date,
        teacher_id=teacher_id,
        student_id=student_id,
    )
    db.add(plan)
    db.flush()
    plans_by_date_student[(plan_date, student_id)] = plan
    return plan


def populate_lesson_plans_from_subjects(
    db: Session,
    teacher_id: int,
    school_year: SchoolDayYear,
    schedule_items: list[WeeklyScheduleItem],
    *,
    preserve_completed: bool = False,
    extra_occupied: dict[int, set[date]] | None = None,
) -> int:
    if not schedule_items:
        return 0

    preserved_messages = _clear_schedule_item_activities(
        db,
        teacher_id,
        school_year,
        schedule_items,
        preserve_completed=preserve_completed,
    )

    existing_plans = (
        db.query(LessonPlan)
        .options(
            joinedload(LessonPlan.activities).joinedload(Activity.completions),
        )
        .filter(
            LessonPlan.teacher_id == teacher_id,
            LessonPlan.plan_date >= school_year.start_date,
            LessonPlan.plan_date <= school_year.end_date,
        )
        .all()
    )
    plans_by_date_student: dict[tuple[date, int], LessonPlan] = {
        (plan.plan_date, plan.student_id): plan for plan in existing_plans
    }

    activities_added = 0
    for item in schedule_items:
        students = [student for student in item.assigned_students if student.is_active]
        if not students:
            continue

        weekdays = parse_weekdays(item.weekdays)
        # Only planned actual school days that match the subject's weekday picker.
        matching = matching_available_days(school_year, weekdays)
        desired = item.lesson_amount or 0

        for student in students:
            completed_dates: list[date] = []
            for plan in existing_plans:
                if plan.student_id != student.id:
                    continue
                for activity in plan.activities:
                    if not activity_matches_schedule_item(activity.title, item):
                        continue
                    if _activity_is_completed(activity, student.id):
                        completed_dates.append(plan.plan_date)

            completed_count = len(completed_dates)
            occupied = set(completed_dates)
            if extra_occupied:
                occupied |= extra_occupied.get(student.id, set())
            free_days = [d for d in matching if d not in occupied]
            still_needed = max(desired - completed_count, 0)
            place_dates = distribute_lesson_dates(free_days, still_needed)

            all_dates = sorted(set(completed_dates) | set(place_dates))
            date_to_number = {day: idx for idx, day in enumerate(all_dates, start=1)}

            for plan in existing_plans:
                if plan.student_id != student.id:
                    continue
                for activity in plan.activities:
                    if not activity_matches_schedule_item(activity.title, item):
                        continue
                    if not _activity_is_completed(activity, student.id):
                        continue
                    numbered = schedule_item_to_activity(
                        item, lesson_number=date_to_number.get(plan.plan_date)
                    )
                    activity.title = numbered["title"]

            for plan_date in place_dates:
                if plan_date not in matching:
                    continue
                plan = _get_or_create_plan(
                    db,
                    plans_by_date_student,
                    teacher_id=teacher_id,
                    plan_date=plan_date,
                    student_id=student.id,
                )
                activity_data = schedule_item_to_activity(
                    item, lesson_number=date_to_number[plan_date]
                )
                if _activity_exists(plan, activity_data["title"]):
                    continue
                next_sort = max((activity.sort_order for activity in plan.activities), default=0) + 1
                _add_activity_to_plan(db, plan, activity_data, sort_order=next_sort)
                db.flush()
                activities_added += 1

    db.flush()
    _restore_preserved_messages(
        db, teacher_id, school_year, schedule_items, preserved_messages
    )
    return activities_added


def reschedule_lessons_after_day_type_change(
    db: Session,
    teacher_id: int,
    school_year: SchoolDayYear,
) -> int:
    """Rebuild subject lessons after day-off/holiday changes, keeping completed work in place.

    Unfinished lessons shift onto later available matching actual school days (respecting
    each subject's weekday picker). Lessons that no longer fit the remaining range are dropped.
    """
    # Clear any leftover plans that somehow landed on non-school days first.
    snap_lesson_plans_to_actual_school_days(db, teacher_id, school_year)

    items = (
        db.query(WeeklyScheduleItem)
        .options(joinedload(WeeklyScheduleItem.assigned_students))
        .filter(WeeklyScheduleItem.teacher_id == teacher_id)
        .order_by(WeeklyScheduleItem.sort_order, WeeklyScheduleItem.id)
        .all()
    )
    if not items:
        return 0
    return populate_lesson_plans_from_subjects(
        db,
        teacher_id,
        school_year,
        items,
        preserve_completed=True,
    )


def count_scheduled_subject_lessons(
    db: Session,
    teacher_id: int,
    school_year: SchoolDayYear,
    item: WeeklyScheduleItem,
    student_id: int,
) -> int:
    plans = (
        db.query(LessonPlan)
        .options(joinedload(LessonPlan.activities))
        .filter(
            LessonPlan.teacher_id == teacher_id,
            LessonPlan.student_id == student_id,
            LessonPlan.plan_date >= school_year.start_date,
            LessonPlan.plan_date <= school_year.end_date,
        )
        .all()
    )
    total = 0
    for plan in plans:
        total += sum(
            1
            for activity in plan.activities
            if activity_matches_schedule_item(activity.title, item)
        )
    return total


def build_subjects_progress_report(
    db: Session,
    teacher_id: int,
    school_year: SchoolDayYear | None,
    schedule_items: list[WeeklyScheduleItem],
) -> list[dict]:
    """Progress-style counts for yearly subjects. Balance may be negative when short on days."""
    if school_year is None:
        return []

    rows: list[dict] = []
    for item in schedule_items:
        weekdays = parse_weekdays(item.weekdays)
        available = len(matching_available_days(school_year, weekdays))
        requested = item.lesson_amount or 0
        balance = available - requested

        students = [student for student in item.assigned_students if student.is_active]
        if students:
            scheduled_counts = [
                count_scheduled_subject_lessons(
                    db, teacher_id, school_year, item, student.id
                )
                for student in students
            ]
            scheduled = min(scheduled_counts) if scheduled_counts else 0
            dropped = max(requested - scheduled, 0)
        else:
            scheduled = 0
            dropped = requested

        rows.append(
            {
                "id": item.id,
                "name": item.name,
                "lessons_per_year": requested,
                "available_days": available,
                "balance": balance,
                "scheduled": scheduled,
                "dropped": dropped,
                "student_count": len(students),
            }
        )
    return rows


def days_off_in_year(school_year: SchoolDayYear) -> list[date]:
    """Return planned day-off dates within the school year."""
    planned_map = {day.day_date: day for day in school_year.planned_days}
    days: list[date] = []
    for day_date in iter_dates_in_range(school_year.start_date, school_year.end_date):
        planned = planned_map.get(day_date)
        if planned is None:
            continue
        day_type = _day_type_value(planned.day_type)
        if day_type in (
            SchoolDayType.school_off.value,
            SchoolDayType.holiday.value,
        ):
            days.append(day_date)
    return days


def shift_unfinished_activity_like_day_off(
    db: Session,
    activity: Activity,
    plan: LessonPlan,
    school_year: SchoolDayYear | None,
    schedule_items: list[WeeklyScheduleItem],
) -> bool:
    """Shift an unfinished lesson forward the same way a day off reschedules subjects.

    For subject-linked lessons, the current date is blocked for unfinished placement and
    the subject's unfinished lessons are rebuilt (completed work stays put), cascading
    later lessons onto the next matching school days.

    For non-subject lessons, the activity moves onto the next actual school day.
    Returns True when a shift was applied.
    """
    if school_year is None:
        return False

    matching_item = next(
        (
            item
            for item in schedule_items
            if activity_matches_schedule_item(activity.title, item)
        ),
        None,
    )

    blocked_date = plan.plan_date
    student_id = plan.student_id
    teacher_id = plan.teacher_id

    if matching_item is not None and parse_weekdays(matching_item.weekdays):
        # Rebuild unfinished subject lessons with this date blocked so they cascade
        # forward (same behavior as marking a day off). Messages are preserved by
        # populate_lesson_plans_from_subjects.
        item = (
            db.query(WeeklyScheduleItem)
            .options(joinedload(WeeklyScheduleItem.assigned_students))
            .filter(WeeklyScheduleItem.id == matching_item.id)
            .first()
        )
        if item is None:
            return False
        populate_lesson_plans_from_subjects(
            db,
            teacher_id,
            school_year,
            [item],
            preserve_completed=True,
            extra_occupied={student_id: {blocked_date}},
        )
        return True

    # Non-subject (or subject without weekdays): move onto the next actual school day
    # that does not already have this activity title.
    candidates = [
        day for day in actual_school_days_in_year(school_year) if day > blocked_date
    ]
    if not candidates:
        return False

    plans_by_key: dict[tuple[date, int], LessonPlan] = {
        (existing.plan_date, existing.student_id): existing
        for existing in db.query(LessonPlan)
        .options(joinedload(LessonPlan.activities))
        .filter(
            LessonPlan.teacher_id == teacher_id,
            LessonPlan.student_id == student_id,
            LessonPlan.plan_date >= school_year.start_date,
            LessonPlan.plan_date <= school_year.end_date,
        )
        .all()
    }

    target = None
    for day in candidates:
        existing = plans_by_key.get((day, student_id))
        if existing is not None and _activity_exists(existing, activity.title):
            continue
        target = _get_or_create_plan(
            db,
            plans_by_key,
            teacher_id=teacher_id,
            plan_date=day,
            student_id=student_id,
        )
        break
    if target is None:
        return False

    next_sort = max((act.sort_order for act in target.activities), default=0) + 1
    activity.lesson_plan_id = target.id
    activity.sort_order = next_sort
    db.flush()

    remaining = db.query(Activity).filter(Activity.lesson_plan_id == plan.id).count()
    if remaining == 0:
        db.delete(plan)
    db.flush()
    return True
