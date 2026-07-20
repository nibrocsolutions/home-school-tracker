from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import PlannedSchoolDay, SchoolDayType, SchoolDayYear

DAY_TYPE_CYCLE = (
    SchoolDayType.weekend,
    SchoolDayType.holiday,
    SchoolDayType.school_off,
    SchoolDayType.sick,
    SchoolDayType.actual_school,
)


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def _observe_holiday(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        d = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def federal_holiday_names_for_year(year: int) -> dict[date, str]:
    entries = [
        (date(year, 1, 1), "New Year's Day"),
        (_nth_weekday(year, 1, 0, 3), "MLK Day"),
        (_nth_weekday(year, 2, 0, 3), "Presidents' Day"),
        (_last_weekday(year, 5, 0), "Memorial Day"),
        (date(year, 6, 19), "Juneteenth"),
        (date(year, 7, 4), "Independence Day"),
        (_nth_weekday(year, 9, 0, 1), "Labor Day"),
        (_nth_weekday(year, 10, 0, 2), "Columbus Day"),
        (date(year, 11, 11), "Veterans Day"),
        (_nth_weekday(year, 11, 3, 4), "Thanksgiving"),
        (date(year, 12, 25), "Christmas"),
    ]
    names: dict[date, str] = {}
    for holiday_date, label in entries:
        names[_observe_holiday(holiday_date)] = label
    return names


def federal_holidays_for_year(year: int) -> set[date]:
    return set(federal_holiday_names_for_year(year).keys())


def holiday_names_in_range(start: date, end: date) -> dict[date, str]:
    names: dict[date, str] = {}
    for year in range(start.year, end.year + 1):
        names.update(federal_holiday_names_for_year(year))
    return {day: label for day, label in names.items() if start <= day <= end}


def holiday_name_for_date(day: date, start: date, end: date) -> str | None:
    if not (start <= day <= end):
        return None
    return holiday_names_in_range(start, end).get(day)


def holidays_in_range(start: date, end: date) -> set[date]:
    holidays: set[date] = set()
    for year in range(start.year, end.year + 1):
        holidays.update(federal_holidays_for_year(year))
    return {d for d in holidays if start <= d <= end}


def default_day_type(d: date, holiday_dates: set[date] | None = None) -> SchoolDayType:
    """Default day type for newly created planned days.

    Federal holidays are NOT auto-marked as holiday — they stay actual school days
    unless the teacher manually edits the day to holiday. Holiday names can still
    be shown as labels on the calendar.
    """
    if is_weekend(d):
        return SchoolDayType.weekend
    return SchoolDayType.actual_school


def count_possible_school_days(start: date, end: date) -> int:
    """Count weekdays in range. Federal holidays count unless marked off manually later."""
    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


def iter_dates_in_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def ensure_planned_days(db: Session, school_year: SchoolDayYear) -> None:
    existing = {day.day_date: day for day in school_year.planned_days}

    for day_date in iter_dates_in_range(school_year.start_date, school_year.end_date):
        if day_date not in existing:
            db.add(
                PlannedSchoolDay(
                    school_day_year_id=school_year.id,
                    day_date=day_date,
                    day_type=default_day_type(day_date),
                    is_completed=False,
                )
            )

    for day_date, planned in existing.items():
        if day_date < school_year.start_date or day_date > school_year.end_date:
            db.delete(planned)


def next_day_type_after_click(
    day_type: SchoolDayType, is_completed: bool
) -> tuple[SchoolDayType, bool]:
    if day_type == SchoolDayType.actual_school and not is_completed:
        return SchoolDayType.actual_school, True
    if day_type == SchoolDayType.actual_school and is_completed:
        return SchoolDayType.school_off, False

    try:
        idx = DAY_TYPE_CYCLE.index(day_type)
    except ValueError:
        idx = -1
    next_type = DAY_TYPE_CYCLE[(idx + 1) % len(DAY_TYPE_CYCLE)]
    return next_type, False


def collect_school_day_attendance(school_year: SchoolDayYear) -> dict:
    holidays = holidays_in_range(school_year.start_date, school_year.end_date)
    holiday_names = holiday_names_in_range(school_year.start_date, school_year.end_date)
    planned_map = {
        day.day_date: day
        for day in school_year.planned_days
        if school_year.start_date <= day.day_date <= school_year.end_date
    }

    by_type: dict[SchoolDayType, list[dict]] = {day_type: [] for day_type in SchoolDayType}
    completed_dates: list[date] = []
    incomplete_actual_dates: list[date] = []

    for day_date in iter_dates_in_range(school_year.start_date, school_year.end_date):
        planned = planned_map.get(day_date)
        if planned is not None:
            day_type = planned.day_type
            is_completed = planned.is_completed
        else:
            day_type = default_day_type(day_date)
            is_completed = False

        entry = {
            "date": day_date,
            "holiday_name": holiday_names.get(day_date),
            "is_completed": is_completed,
        }
        by_type[day_type].append(entry)

        if day_type == SchoolDayType.actual_school:
            if is_completed:
                completed_dates.append(day_date)
            else:
                incomplete_actual_dates.append(day_date)

    counts = planned_day_counts(school_year)
    required_days = school_year.required_days
    remaining_days = max(required_days - counts["completed_count"], 0)

    return {
        "start_date": school_year.start_date,
        "end_date": school_year.end_date,
        "required_days": required_days,
        "counts": counts,
        "remaining_days": remaining_days,
        "by_type": by_type,
        "completed_dates": completed_dates,
        "incomplete_actual_dates": incomplete_actual_dates,
    }


def _day_type_value(day_type: SchoolDayType | str | None) -> str:
    if day_type is None:
        return ""
    if isinstance(day_type, SchoolDayType):
        return day_type.value
    return str(getattr(day_type, "value", day_type))


def planned_day_counts(school_year: SchoolDayYear) -> dict[str, int]:
    planned = [
        day
        for day in school_year.planned_days
        if school_year.start_date <= day.day_date <= school_year.end_date
    ]
    actual_school = [
        day for day in planned if _day_type_value(day.day_type) == SchoolDayType.actual_school.value
    ]
    school_off = [
        day for day in planned if _day_type_value(day.day_type) == SchoolDayType.school_off.value
    ]
    sick = [day for day in planned if _day_type_value(day.day_type) == SchoolDayType.sick.value]
    completed = [day for day in actual_school if day.is_completed]
    return {
        "planned_actual_count": len(actual_school),
        "planned_school_off_count": len(school_off),
        "planned_sick_count": len(sick),
        "completed_count": len(completed),
        "possible_days": count_possible_school_days(
            school_year.start_date, school_year.end_date
        ),
    }
