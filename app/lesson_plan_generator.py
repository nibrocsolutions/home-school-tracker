from datetime import date, datetime, timedelta

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

MOVED_LESSONS_PLACEHOLDER_TITLE = "Lessons moved"


def _is_moved_lessons_placeholder(activity: Activity) -> bool:
    return activity.title == MOVED_LESSONS_PLACEHOLDER_TITLE


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
        message = ""
        message_read_at = None
        if completion and completion.student_message and completion.student_message.strip():
            message = completion.student_message.strip()
            message_read_at = completion.message_read_at
        link = (activity.external_link or "").strip() or None
        notes = (activity.teacher_notes or "").strip() or None
        if message or link or notes:
            student_bucket.append(
                {
                    "student_message": message or None,
                    "message_read_at": message_read_at,
                    "external_link": link,
                    "teacher_notes": notes,
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


def _transfer_messages_to_activity(
    db: Session,
    source: Activity,
    target: Activity,
) -> None:
    """Copy student/teacher messages from source onto target before source is deleted."""
    for src_completion in list(source.completions):
        message = (src_completion.student_message or "").strip()
        if not message:
            continue
        dest = next(
            (
                entry
                for entry in target.completions
                if entry.student_id == src_completion.student_id
            ),
            None,
        )
        if dest is None:
            db.add(
                ActivityCompletion(
                    activity_id=target.id,
                    student_id=src_completion.student_id,
                    completed=bool(src_completion.completed),
                    completed_at=src_completion.completed_at,
                    student_message=message,
                    message_read_at=src_completion.message_read_at,
                )
            )
            continue
        existing = (dest.student_message or "").strip()
        if not existing:
            dest.student_message = message
            dest.message_read_at = src_completion.message_read_at
        elif message not in existing:
            dest.student_message = f"{existing}\n\n{message}"
            if src_completion.message_read_at is None:
                dest.message_read_at = None


def _attach_message_payload(
    db: Session,
    activity: Activity,
    student_id: int,
    payload: dict,
) -> None:
    message = (payload.get("student_message") or "").strip()
    if not message:
        return
    completion = next(
        (entry for entry in activity.completions if entry.student_id == student_id),
        None,
    )
    if completion is None:
        db.add(
            ActivityCompletion(
                activity_id=activity.id,
                student_id=student_id,
                completed=False,
                student_message=message,
                message_read_at=payload.get("message_read_at"),
            )
        )
        return
    existing = (completion.student_message or "").strip()
    if not existing:
        completion.student_message = message
        completion.message_read_at = payload.get("message_read_at")
    elif message not in existing:
        completion.student_message = f"{existing}\n\n{message}"
        if payload.get("message_read_at") is None:
            completion.message_read_at = None


def _restore_preserved_messages(
    db: Session,
    teacher_id: int,
    school_year: SchoolDayYear,
    schedule_items: list[WeeklyScheduleItem],
    preserved: dict[int, dict[int, list[dict | None]]],
) -> None:
    """Re-attach preserved messages/links/notes onto rebuilt unfinished activities."""
    if not preserved:
        return

    # Newly added activities are written by FK only; expire so joinedload sees them.
    db.expire_all()

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
                    # Only unfinished rebuilt lessons receive shifted fields.
                    if _activity_is_completed(activity, student_id):
                        continue
                    rebuilt.append(activity)

            paired = list(zip(rebuilt, payloads))
            for activity, payload in paired:
                if not payload:
                    continue
                link = (payload.get("external_link") or "").strip()
                if link:
                    activity.external_link = link
                notes = (payload.get("teacher_notes") or "").strip()
                if notes:
                    activity.teacher_notes = notes
                if (payload.get("student_message") or "").strip():
                    _attach_message_payload(db, activity, student_id, payload)

            # Never drop messages when fewer lessons remain after a day-off rebuild.
            leftovers = [
                payload
                for payload in payloads[len(rebuilt) :]
                if payload and (payload.get("student_message") or "").strip()
            ]
            if leftovers and rebuilt:
                for payload in leftovers:
                    _attach_message_payload(db, rebuilt[-1], student_id, payload)
            elif leftovers:
                host = next(
                    (
                        activity
                        for plan in plans
                        if plan.student_id == student_id
                        for activity in plan.activities
                        if _is_moved_lessons_placeholder(activity)
                    ),
                    None,
                )
                if host is None:
                    plan = next((p for p in plans if p.student_id == student_id), None)
                    if plan is None:
                        plan = LessonPlan(
                            title=_auto_plan_title(school_year.start_date),
                            description=None,
                            plan_date=school_year.start_date,
                            teacher_id=teacher_id,
                            student_id=student_id,
                        )
                        db.add(plan)
                        db.flush()
                        plans.append(plan)
                    host = Activity(
                        lesson_plan_id=plan.id,
                        title=MOVED_LESSONS_PLACEHOLDER_TITLE,
                        description="Preserved messages from lessons that were rescheduled.",
                        sort_order=max((a.sort_order for a in plan.activities), default=0) + 1,
                        activity_type=ActivityType.regular,
                        is_required=False,
                    )
                    db.add(host)
                    db.flush()
                for payload in leftovers:
                    _attach_message_payload(db, host, student_id, payload)
    db.flush()


def _auto_plan_title(plan_date: date) -> str:
    return plan_date.strftime("%A, %B %d, %Y")


def _merge_plan_into(db: Session, source: LessonPlan, target: LessonPlan) -> None:
    """Move activities from source into target, then delete source."""
    next_sort = max((activity.sort_order for activity in target.activities), default=0)
    for activity in list(source.activities):
        existing = next(
            (entry for entry in target.activities if entry.title == activity.title),
            None,
        )
        if existing is not None:
            _transfer_messages_to_activity(db, activity, existing)
            db.delete(activity)
            continue
        next_sort += 1
        activity.lesson_plan = target
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
            external_link=activity_data.get("external_link") or None,
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
            # Days kept as placeholders after "Not finished" must stay blocked so
            # later rebuilds do not place the lesson back on the original day.
            for plan in existing_plans:
                if plan.student_id != student.id:
                    continue
                if any(_is_moved_lessons_placeholder(activity) for activity in plan.activities):
                    occupied.add(plan.plan_date)
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


def _unfinished_move_message(lesson_title: str, from_date: date, to_date: date) -> str:
    return (
        f'Lesson unfinished: "{lesson_title}" was moved from '
        f"{from_date.strftime('%A, %B %d, %Y')} to {to_date.strftime('%A, %B %d, %Y')}."
    )


def _set_teacher_message_on_activity(
    db: Session,
    activity: Activity,
    student_id: int,
    message: str,
    *,
    append: bool = False,
) -> None:
    completion = (
        db.query(ActivityCompletion)
        .filter(
            ActivityCompletion.activity_id == activity.id,
            ActivityCompletion.student_id == student_id,
        )
        .first()
    )
    if completion is None:
        db.add(
            ActivityCompletion(
                activity_id=activity.id,
                student_id=student_id,
                completed=True,
                completed_at=datetime.utcnow(),
                student_message=message,
                message_read_at=None,
            )
        )
        return

    if append and completion.student_message and message not in completion.student_message:
        completion.student_message = f"{completion.student_message.strip()}\n\n{message}"
    else:
        completion.student_message = message
    completion.message_read_at = None
    completion.completed = True
    if completion.completed_at is None:
        completion.completed_at = datetime.utcnow()


def _ensure_moved_lessons_placeholder(
    db: Session,
    *,
    teacher_id: int,
    student_id: int,
    plan_date: date,
    lesson_title: str,
    from_date: date,
    to_date: date,
) -> Activity:
    """Keep an emptied (or partially cleared) school day present with a notice lesson."""
    plan = (
        db.query(LessonPlan)
        .options(joinedload(LessonPlan.activities))
        .filter(
            LessonPlan.teacher_id == teacher_id,
            LessonPlan.student_id == student_id,
            LessonPlan.plan_date == plan_date,
        )
        .first()
    )
    if plan is None:
        plan = LessonPlan(
            title=_auto_plan_title(plan_date),
            description=None,
            plan_date=plan_date,
            teacher_id=teacher_id,
            student_id=student_id,
        )
        db.add(plan)
        db.flush()

    placeholder = next(
        (act for act in plan.activities if _is_moved_lessons_placeholder(act)),
        None,
    )
    real_left = _count_real_activities(plan)
    if real_left == 0:
        description = (
            "Lessons were planned for this day, but they were moved to a later school day "
            f'because "{lesson_title}" was marked unfinished.'
        )
    else:
        description = (
            f'"{lesson_title}" was marked unfinished and moved to '
            f"{to_date.strftime('%A, %B %d, %Y')}."
        )
    if placeholder is None:
        next_sort = max((act.sort_order for act in plan.activities), default=0) + 1
        placeholder = Activity(
            lesson_plan_id=plan.id,
            title=MOVED_LESSONS_PLACEHOLDER_TITLE,
            description=description,
            sort_order=next_sort,
            activity_type=ActivityType.regular,
            is_required=False,
        )
        db.add(placeholder)
        db.flush()
    else:
        placeholder.description = description
        placeholder.is_required = False

    _set_teacher_message_on_activity(
        db,
        placeholder,
        student_id,
        _unfinished_move_message(lesson_title, from_date, to_date),
        append=True,
    )
    db.flush()
    return placeholder


def _count_real_activities(plan: LessonPlan | None) -> int:
    if plan is None:
        return 0
    return sum(1 for act in plan.activities if not _is_moved_lessons_placeholder(act))


def _notify_unfinished_move(
    db: Session,
    *,
    teacher_id: int,
    student_id: int,
    source_date: date,
    target_date: date,
    lesson_title: str,
) -> None:
    """Create a separate teacher message for an unfinished move on the source day.

    When the source day has no remaining real lessons, the notice doubles as a
    placeholder so the day still appears as a planned school day.
    """
    _ensure_moved_lessons_placeholder(
        db,
        teacher_id=teacher_id,
        student_id=student_id,
        plan_date=source_date,
        lesson_title=lesson_title,
        from_date=source_date,
        to_date=target_date,
    )


def _capture_activity_message(
    db: Session, activity_id: int, student_id: int
) -> dict | None:
    completion = (
        db.query(ActivityCompletion)
        .filter(
            ActivityCompletion.activity_id == activity_id,
            ActivityCompletion.student_id == student_id,
        )
        .first()
    )
    if not completion:
        return None
    message = (completion.student_message or "").strip()
    if not message:
        return None
    return {
        "student_message": message,
        "message_read_at": completion.message_read_at,
    }


def _apply_message_to_activity(
    db: Session,
    activity: Activity,
    student_id: int,
    payload: dict,
) -> None:
    message = (payload.get("student_message") or "").strip()
    if not message:
        return
    completion = (
        db.query(ActivityCompletion)
        .filter(
            ActivityCompletion.activity_id == activity.id,
            ActivityCompletion.student_id == student_id,
        )
        .first()
    )
    if completion is None:
        db.add(
            ActivityCompletion(
                activity_id=activity.id,
                student_id=student_id,
                completed=False,
                student_message=message,
                message_read_at=payload.get("message_read_at"),
            )
        )
    else:
        completion.student_message = message
        completion.message_read_at = payload.get("message_read_at")


def _unfinished_matching_activities(
    db: Session,
    *,
    teacher_id: int,
    student_id: int,
    school_year: SchoolDayYear,
    item: WeeklyScheduleItem,
) -> list[tuple[LessonPlan, Activity]]:
    plans = (
        db.query(LessonPlan)
        .options(joinedload(LessonPlan.activities).joinedload(Activity.completions))
        .filter(
            LessonPlan.teacher_id == teacher_id,
            LessonPlan.student_id == student_id,
            LessonPlan.plan_date >= school_year.start_date,
            LessonPlan.plan_date <= school_year.end_date,
        )
        .order_by(LessonPlan.plan_date, LessonPlan.id)
        .all()
    )
    rows: list[tuple[LessonPlan, Activity]] = []
    for plan in plans:
        for activity in sorted(plan.activities, key=lambda a: (a.sort_order, a.id)):
            if not activity_matches_schedule_item(activity.title, item):
                continue
            if _activity_is_completed(activity, student_id):
                continue
            rows.append((plan, activity))
    return rows


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
    later lessons onto the next matching school days. Student messages move with the lesson.

    For non-subject lessons, the activity moves onto the next actual school day.
    Creates a separate teacher message with from/to dates. If the source day ends with
    no real lessons, a placeholder keeps it as a school day in lesson views.
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
    lesson_title = activity.title
    saved_message = _capture_activity_message(db, activity.id, student_id)

    if matching_item is not None:
        weekdays = parse_weekdays(matching_item.weekdays) or set(range(5))
        # Remember this lesson's position among unfinished matching lessons so the
        # saved message can be reattached to the same logical lesson after rebuild.
        before_rows = _unfinished_matching_activities(
            db,
            teacher_id=teacher_id,
            student_id=student_id,
            school_year=school_year,
            item=matching_item,
        )
        shift_index = next(
            (
                idx
                for idx, (_plan, act) in enumerate(before_rows)
                if act.id == activity.id
            ),
            0,
        )

        item = (
            db.query(WeeklyScheduleItem)
            .options(joinedload(WeeklyScheduleItem.assigned_students))
            .filter(WeeklyScheduleItem.id == matching_item.id)
            .first()
        )
        if item is None:
            return False

        # Ensure weekday matching works even when the subject picker is still empty.
        original_weekdays = item.weekdays
        if not parse_weekdays(item.weekdays):
            item.weekdays = ",".join(str(day) for day in sorted(weekdays))

        try:
            populate_lesson_plans_from_subjects(
                db,
                teacher_id,
                school_year,
                [item],
                preserve_completed=True,
                extra_occupied={student_id: {blocked_date}},
            )
        finally:
            if item.weekdays != original_weekdays:
                item.weekdays = original_weekdays

        after_rows = _unfinished_matching_activities(
            db,
            teacher_id=teacher_id,
            student_id=student_id,
            school_year=school_year,
            item=item,
        )
        if after_rows:
            target_idx = min(shift_index, len(after_rows) - 1)
            host_plan, host_activity = after_rows[target_idx]
            target_date = host_plan.plan_date
            if saved_message:
                _apply_message_to_activity(db, host_activity, student_id, saved_message)
        else:
            later_days = [
                day for day in actual_school_days_in_year(school_year) if day > blocked_date
            ]
            target_date = later_days[0] if later_days else blocked_date

        _notify_unfinished_move(
            db,
            teacher_id=teacher_id,
            student_id=student_id,
            source_date=blocked_date,
            target_date=target_date,
            lesson_title=lesson_title,
        )
        db.flush()
        return True

    # Non-subject: move onto the next actual school day that does not already have
    # this activity title. Completions stay on the same activity row.
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
    # Assign via relationship so SQLAlchemy syncs both collections (avoid stale
    # source-plan collections writing the activity back onto the original day).
    activity.lesson_plan = target
    activity.sort_order = next_sort
    db.flush()
    db.expire(plan, ["activities"])
    db.expire(target, ["activities"])

    if saved_message:
        _apply_message_to_activity(db, activity, student_id, saved_message)

    # Do not delete an emptied source plan — placeholder + teacher notice keeps the day.
    _notify_unfinished_move(
        db,
        teacher_id=teacher_id,
        student_id=student_id,
        source_date=blocked_date,
        target_date=target.plan_date,
        lesson_title=lesson_title,
    )
    db.flush()
    return True
