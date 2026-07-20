from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from app.models import Activity, ActivityType, LessonPlan, SchoolDayType, SchoolDayYear, WeeklyScheduleItem
from app.school_year_utils import iter_dates_in_range
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


def actual_school_days_in_year(school_year: SchoolDayYear) -> list[date]:
    planned_map = {day.day_date: day for day in school_year.planned_days}
    days: list[date] = []
    for day_date in iter_dates_in_range(school_year.start_date, school_year.end_date):
        planned = planned_map.get(day_date)
        if planned is None:
            continue
        if planned.day_type == SchoolDayType.actual_school:
            days.append(day_date)
    return days


def matching_available_days(
    school_year: SchoolDayYear, weekdays: set[int]
) -> list[date]:
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
) -> None:
    """Remove previously auto-populated activities for the given subjects so they can be rebuilt."""
    if not schedule_items:
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
        .all()
    )

    empty_plans: list[LessonPlan] = []
    for plan in plans:
        remaining = []
        for activity in list(plan.activities):
            matches = any(
                activity_matches_schedule_item(activity.title, item) for item in schedule_items
            )
            if matches and not (
                preserve_completed and _activity_is_completed(activity, plan.student_id)
            ):
                db.delete(activity)
            else:
                remaining.append(activity)
        if not remaining:
            empty_plans.append(plan)

    db.flush()
    for plan in empty_plans:
        db.delete(plan)
    db.flush()
    db.expire_all()


def shift_lesson_plans_by_days(
    db: Session,
    teacher_id: int,
    old_start: date,
    old_end: date,
    day_delta: int,
) -> int:
    """Move lesson plans within the previous school-year range by day_delta days."""
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
        auto_title = old_date.strftime("%A, %B %d, %Y")
        if plan.title == auto_title:
            plan.title = new_date.strftime("%A, %B %d, %Y")
        plan.plan_date = new_date
        shifted += 1

    db.flush()
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
            audio_url=activity_data["audio_url"] or None,
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
        title=plan_date.strftime("%A, %B %d, %Y"),
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
) -> int:
    if not schedule_items:
        return 0

    _clear_schedule_item_activities(
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
    return activities_added


def reschedule_lessons_after_day_type_change(
    db: Session,
    teacher_id: int,
    school_year: SchoolDayYear,
) -> int:
    """Rebuild subject lessons after sick/skip/off changes, keeping completed work in place.

    Unfinished lessons shift onto later available matching days. Lessons that no longer fit
    the remaining range are dropped.
    """
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
