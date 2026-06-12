from calendar import monthcalendar
from datetime import date

from app.calendar_utils import shift_ref_date
from app.models import SchoolDayType, SchoolDayYear
from app.school_year_utils import count_possible_school_days, default_day_type, holidays_in_range


def parse_cal_month(value: str | None, fallback: date) -> date:
    if value:
        try:
            parts = value.split("-")
            if len(parts) >= 2:
                return date(int(parts[0]), int(parts[1]), 1)
        except ValueError:
            pass
    return fallback.replace(day=1)


def default_cal_month(school_year: SchoolDayYear | None) -> date:
    if school_year is None:
        return date.today().replace(day=1)
    return school_year.start_date.replace(day=1)


def planned_days_map(school_year: SchoolDayYear) -> dict[date, dict]:
    return {
        day.day_date: {
            "day_type": day.day_type,
            "is_completed": day.is_completed,
        }
        for day in school_year.planned_days
        if school_year.start_date <= day.day_date <= school_year.end_date
    }


def build_school_day_month_grid(
    cal_month: date,
    school_year: SchoolDayYear | None,
    planned: dict[date, dict],
) -> list[list[dict]]:
    holidays = (
        holidays_in_range(school_year.start_date, school_year.end_date)
        if school_year
        else set()
    )
    weeks = monthcalendar(cal_month.year, cal_month.month)
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
                        "is_today": False,
                    }
                )
            else:
                d = date(cal_month.year, cal_month.month, day_num)
                in_range = False
                day_type = None
                is_completed = False
                if school_year is not None:
                    in_range = school_year.start_date <= d <= school_year.end_date
                    if in_range:
                        if d in planned:
                            day_type = planned[d]["day_type"]
                            is_completed = planned[d]["is_completed"]
                        else:
                            day_type = default_day_type(d, holidays)
                row.append(
                    {
                        "day": day_num,
                        "date": d,
                        "in_range": in_range,
                        "day_type": day_type,
                        "is_completed": is_completed,
                        "is_today": d == date.today(),
                    }
                )
        grid.append(row)
    return grid


def build_school_day_context(
    school_year: SchoolDayYear | None,
    cal_month_param: str | None,
) -> dict:
    cal_month = parse_cal_month(
        cal_month_param,
        default_cal_month(school_year),
    )
    planned = planned_days_map(school_year) if school_year else {}
    counts = {
        "planned_actual_count": 0,
        "completed_count": 0,
        "possible_days": 0,
    }
    if school_year:
        actual_school = [
            info
            for info in planned.values()
            if info["day_type"] == SchoolDayType.actual_school
        ]
        counts = {
            "planned_actual_count": len(actual_school),
            "completed_count": sum(1 for info in actual_school if info["is_completed"]),
            "possible_days": count_possible_school_days(
                school_year.start_date, school_year.end_date
            ),
        }

    required_days = school_year.required_days if school_year else 180
    remaining_days = max(required_days - counts["completed_count"], 0)

    prev_month = shift_ref_date(cal_month, "monthly", -1)
    next_month = shift_ref_date(cal_month, "monthly", 1)

    return {
        "school_year": school_year,
        "cal_month": cal_month,
        "cal_month_label": cal_month.strftime("%B %Y"),
        "cal_month_param": cal_month.strftime("%Y-%m"),
        "prev_cal_month": prev_month.strftime("%Y-%m"),
        "next_cal_month": next_month.strftime("%Y-%m"),
        "school_day_grid": build_school_day_month_grid(cal_month, school_year, planned),
        "possible_days": counts["possible_days"],
        "planned_actual_count": counts["planned_actual_count"],
        "completed_count": counts["completed_count"],
        "required_days": required_days,
        "remaining_days": remaining_days,
    }
