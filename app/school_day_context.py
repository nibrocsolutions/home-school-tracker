from calendar import monthcalendar
from datetime import date

from app.calendar_utils import shift_ref_date
from app.models import SchoolDayYear


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
    today = date.today()
    if school_year is None:
        return today.replace(day=1)
    if today < school_year.start_date:
        return school_year.start_date.replace(day=1)
    if today > school_year.end_date:
        return school_year.end_date.replace(day=1)
    return today.replace(day=1)


def approved_dates_in_range(school_year: SchoolDayYear) -> set[date]:
    return {
        day.day_date
        for day in school_year.approved_days
        if school_year.start_date <= day.day_date <= school_year.end_date
    }


def build_school_day_month_grid(
    cal_month: date,
    school_year: SchoolDayYear | None,
    approved: set[date],
) -> list[list[dict]]:
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
                        "is_approved": False,
                        "is_today": False,
                    }
                )
            else:
                d = date(cal_month.year, cal_month.month, day_num)
                in_range = False
                if school_year is not None:
                    in_range = school_year.start_date <= d <= school_year.end_date
                row.append(
                    {
                        "day": day_num,
                        "date": d,
                        "in_range": in_range,
                        "is_approved": d in approved,
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
    approved = approved_dates_in_range(school_year) if school_year else set()
    approved_count = len(approved)
    required_days = school_year.required_days if school_year else 180
    remaining_days = max(required_days - approved_count, 0)

    prev_month = shift_ref_date(cal_month, "monthly", -1)
    next_month = shift_ref_date(cal_month, "monthly", 1)

    return {
        "school_year": school_year,
        "cal_month": cal_month,
        "cal_month_label": cal_month.strftime("%B %Y"),
        "cal_month_param": cal_month.strftime("%Y-%m"),
        "prev_cal_month": prev_month.strftime("%Y-%m"),
        "next_cal_month": next_month.strftime("%Y-%m"),
        "school_day_grid": build_school_day_month_grid(cal_month, school_year, approved),
        "approved_count": approved_count,
        "required_days": required_days,
        "remaining_days": remaining_days,
    }
