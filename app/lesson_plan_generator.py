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
    if lesson_amount <= 0 or not matching_days:
        return []
    if lesson_amount >= len(matching_days):
        return matching_days
    step = len(matching_days) / lesson_amount
    return [matching_days[int(i * step)] for i in range(lesson_amount)]


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


def build_subject_assignments(
    school_year: SchoolDayYear,
    schedule_items: list[WeeklyScheduleItem],
) -> dict[date, list[dict]]:
    actual_days = actual_school_days_in_year(school_year)
    assignments: dict[date, list[dict]] = {}

    for item in schedule_items:
        lesson_amount = item.lesson_amount or 0
        if lesson_amount <= 0:
            continue
        weekdays = parse_weekdays(item.weekdays)
        if not weekdays:
            continue

        matching = [d for d in actual_days if d.weekday() in weekdays]
        selected_dates = distribute_lesson_dates(matching, lesson_amount)
        for lesson_number, day_date in enumerate(selected_dates, start=1):
            activity = schedule_item_to_activity(item, lesson_number=lesson_number)
            assignments.setdefault(day_date, []).append(activity)

    return assignments


def _activity_exists(plan: LessonPlan, title: str) -> bool:
    return any(activity.title == title for activity in plan.activities)


def _clear_schedule_item_activities(
    db: Session,
    teacher_id: int,
    school_year: SchoolDayYear,
    schedule_items: list[WeeklyScheduleItem],
) -> None:
    """Remove previously auto-populated activities for the given subjects so they can be rebuilt."""
    if not schedule_items:
        return

    plans = (
        db.query(LessonPlan)
        .options(joinedload(LessonPlan.activities))
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
            if any(activity_matches_schedule_item(activity.title, item) for item in schedule_items):
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


def populate_lesson_plans_from_subjects(
    db: Session,
    teacher_id: int,
    school_year: SchoolDayYear,
    schedule_items: list[WeeklyScheduleItem],
) -> int:
    if not schedule_items:
        return 0

    # Rebuild from the current subject settings so weekday / amount changes replace old data.
    _clear_schedule_item_activities(db, teacher_id, school_year, schedule_items)

    existing_plans = (
        db.query(LessonPlan)
        .options(joinedload(LessonPlan.activities))
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

        item_assignments = build_subject_assignments(school_year, [item])
        for plan_date, activities in sorted(item_assignments.items()):
            title = plan_date.strftime("%A, %B %d, %Y")
            for student in students:
                plan = plans_by_date_student.get((plan_date, student.id))
                if plan is None:
                    plan = LessonPlan(
                        title=title,
                        description=None,
                        plan_date=plan_date,
                        teacher_id=teacher_id,
                        student_id=student.id,
                    )
                    db.add(plan)
                    db.flush()
                    plans_by_date_student[(plan_date, student.id)] = plan

                next_sort = max((activity.sort_order for activity in plan.activities), default=0)
                for activity_data in activities:
                    if _activity_exists(plan, activity_data["title"]):
                        continue
                    next_sort += 1
                    try:
                        activity_type = ActivityType(activity_data["activity_type"])
                    except ValueError:
                        activity_type = ActivityType.regular
                    db.add(
                        Activity(
                            lesson_plan_id=plan.id,
                            title=activity_data["title"],
                            description=activity_data["description"] or None,
                            sort_order=next_sort,
                            activity_type=activity_type,
                            audio_url=activity_data["audio_url"] or None,
                            external_link=activity_data["external_link"] or None,
                        )
                    )
                    activities_added += 1

    return activities_added
