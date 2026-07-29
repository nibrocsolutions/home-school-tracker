from calendar import SUNDAY, Calendar
from datetime import date, timedelta

from app.calendar_utils import (
    month_end,
    month_start,
    shift_ref_date,
    school_week_dates,
    school_week_end,
    school_week_start,
)
from app.models import LessonPlan, SchoolDayType, SchoolDayYear
from app.school_day_context import default_cal_month, parse_cal_month, planned_days_map
from app.school_year_utils import default_day_type, holiday_names_in_range, holidays_in_range


def build_lesson_planning_month_grid(
    cal_month: date,
    school_year: SchoolDayYear | None,
    planned: dict[date, dict],
    plan_dates: set[date],
) -> list[list[dict]]:
    holidays = (
        holidays_in_range(school_year.start_date, school_year.end_date)
        if school_year
        else set()
    )
    holiday_names = (
        holiday_names_in_range(school_year.start_date, school_year.end_date)
        if school_year
        else {}
    )
    weeks = Calendar(firstweekday=SUNDAY).monthdayscalendar(cal_month.year, cal_month.month)
    grid = []
    for week in weeks:
        row = []
        for day_num in week:
            if day_num == 0:
                row.append(
                    {
                        "day": None,
                        "date": None,
                        "in_range": False,
                        "day_type": None,
                        "is_completed": False,
                        "holiday_name": None,
                        "is_today": False,
                        "has_plans": False,
                    }
                )
            else:
                d = date(cal_month.year, cal_month.month, day_num)
                in_range = False
                day_type = None
                is_completed = False
                holiday_name = None
                if school_year is not None:
                    in_range = school_year.start_date <= d <= school_year.end_date
                    holiday_name = holiday_names.get(d)
                    if in_range:
                        if d in planned:
                            day_type = planned[d]["day_type"]
                            is_completed = planned[d]["is_completed"]
                        else:
                            day_type = default_day_type(d)
                row.append(
                    {
                        "day": day_num,
                        "date": d,
                        "in_range": in_range,
                        "day_type": day_type,
                        "is_completed": is_completed,
                        "holiday_name": holiday_name,
                        "is_today": d == date.today(),
                        "has_plans": d in plan_dates,
                    }
                )
        grid.append(row)
    return grid


def plans_for_date(plans: list[LessonPlan], plan_date: date) -> list[LessonPlan]:
    return [plan for plan in plans if plan.plan_date == plan_date]


def _serialize_plan_activities(plan: LessonPlan) -> list[dict]:
    from app.activity_fields import serialize_custom_fields, parse_custom_fields
    from app.media_library import (
        activity_external_web_links,
        activity_media_urls,
        serialize_external_links,
        serialize_media_attachments,
    )

    serialized = []
    for activity in sorted(plan.activities, key=lambda a: a.sort_order):
        media_urls = activity_media_urls(
            media_attachments=getattr(activity, "media_attachments", None),
            external_link=activity.external_link,
            audio_url=activity.audio_url,
        )
        web_links = activity_external_web_links(activity.external_link)
        custom_fields = parse_custom_fields(getattr(activity, "custom_fields", None))
        serialized.append(
            {
                "title": activity.title,
                "description": activity.description or "",
                "activity_type": activity.activity_type.value,
                "teacher_notes": activity.teacher_notes or "",
                "external_link": serialize_external_links(web_links) or "",
                "media_attachments": serialize_media_attachments(media_urls) or "",
                "media_urls": media_urls,
                "custom_fields": serialize_custom_fields(custom_fields) or "",
            }
        )
    return serialized


def _is_day_off(day: date, planned: dict[date, dict], school_year: SchoolDayYear | None) -> bool:
    if school_year is None:
        return False
    if not (school_year.start_date <= day <= school_year.end_date):
        return False
    entry = planned.get(day)
    day_type = entry["day_type"] if entry else default_day_type(day)
    if isinstance(day_type, SchoolDayType):
        return day_type in (SchoolDayType.school_off, SchoolDayType.holiday)
    return str(day_type) in (
        SchoolDayType.school_off.value,
        SchoolDayType.holiday.value,
    )


def _school_weeks_in_month(
    cal_month: date,
    *,
    plan_dates: set[date],
    planned: dict[date, dict],
    school_year: SchoolDayYear | None,
) -> list[dict]:
    """Return Mon-Fri school weeks for the month that have plans or are fully days off.

    Weeks span full Mon-Fri even when they cross month boundaries (e.g. Aug 31–Sep 4).
    A week is listed when any Mon-Fri day falls in the calendar month.
    """
    m_start = month_start(cal_month)
    m_end = month_end(cal_month)
    weeks: list[dict] = []
    seen_mondays: set[date] = set()

    # Walk every date in the month; collect unique Mon-Fri school weeks that touch it.
    day = m_start
    while day <= m_end:
        monday = school_week_start(day)
        if monday not in seen_mondays:
            seen_mondays.add(monday)
            school_days = school_week_dates(monday)
            friday = school_week_end(monday)
            # Week must overlap this calendar month on a weekday
            if any(m_start <= d <= m_end for d in school_days):
                has_plans = any(d in plan_dates for d in school_days)
                all_off = all(
                    _is_day_off(d, planned, school_year) for d in school_days
                )
                if has_plans or all_off:
                    if monday.month == friday.month:
                        label = f"{monday.strftime('%b %d')} - {friday.strftime('%d')}"
                    else:
                        label = (
                            f"{monday.strftime('%b %d')} - {friday.strftime('%b %d')}"
                        )
                    weeks.append({
                        "ref_date": monday.isoformat(),
                        "label": label,
                    })
        day += timedelta(days=1)

    weeks.sort(key=lambda w: w["ref_date"])
    return weeks


def build_lesson_planning_context(
    school_year: SchoolDayYear | None,
    plans: list[LessonPlan],
    cal_month_param: str | None,
    plan_date_param: str | None,
) -> dict:
    cal_month = parse_cal_month(
        cal_month_param,
        default_cal_month(school_year),
    )
    planned = planned_days_map(school_year) if school_year else {}
    plan_dates = {plan.plan_date for plan in plans}
    month_start_date = month_start(cal_month)
    month_end_date = month_end(cal_month)
    month_plans = [plan for plan in plans if month_start_date <= plan.plan_date <= month_end_date]

    plan_date = None
    if plan_date_param:
        try:
            plan_date = date.fromisoformat(plan_date_param)
        except ValueError:
            plan_date = None

    editor_plans = plans_for_date(plans, plan_date) if plan_date and school_year else []
    editor_context = None
    if plan_date and school_year and editor_plans:
        student_plans = []
        for plan in sorted(
            editor_plans,
            key=lambda p: (
                (p.student.last_name if p.student else ""),
                (p.student.first_name if p.student else ""),
                p.student_id,
            ),
        ):
            student_name = plan.student.full_name if plan.student else f"Student #{plan.student_id}"
            student_plans.append(
                {
                    "student_id": plan.student_id,
                    "student_name": student_name,
                    "title": plan.title,
                    "description": plan.description or "",
                    "activities": _serialize_plan_activities(plan),
                }
            )
        editor_context = {
            "student_plans": student_plans,
            "student_ids": [plan["student_id"] for plan in student_plans],
            "is_edit": True,
        }
    elif plan_date and school_year:
        editor_context = {
            "student_plans": [],
            "student_ids": [],
            "is_edit": False,
            "default_title": plan_date.strftime("%A, %B %d, %Y"),
        }

    prev_month = shift_ref_date(cal_month, "monthly", -1)
    next_month = shift_ref_date(cal_month, "monthly", 1)

    return {
        "school_year": school_year,
        "cal_month": cal_month,
        "cal_month_label": cal_month.strftime("%B %Y"),
        "cal_month_param": cal_month.strftime("%Y-%m"),
        "prev_cal_month": prev_month.strftime("%Y-%m"),
        "next_cal_month": next_month.strftime("%Y-%m"),
        "planning_grid": build_lesson_planning_month_grid(
            cal_month, school_year, planned, plan_dates
        ),
        "month_plans": month_plans,
        "plan_date": plan_date,
        "plan_date_param": plan_date.isoformat() if plan_date else "",
        "editor_context": editor_context,
        "pdf_ref_date": cal_month.isoformat(),
        "pdf_weeks": _school_weeks_in_month(
            cal_month,
            plan_dates=plan_dates,
            planned=planned,
            school_year=school_year,
        ),
        "school_day_type_labels": {
            SchoolDayType.actual_school: "School days",
            SchoolDayType.school_off: "Days off",
            SchoolDayType.holiday: "Days off",
            SchoolDayType.weekend: "Weekends",
        },
    }
