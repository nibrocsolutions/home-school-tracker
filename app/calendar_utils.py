from calendar import monthcalendar
from datetime import date, timedelta


def parse_ref_date(value: str | None) -> date:
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return date.today()


def week_start(ref: date) -> date:
    return ref - timedelta(days=ref.weekday())


def week_end(ref: date) -> date:
    return week_start(ref) + timedelta(days=6)


def month_start(ref: date) -> date:
    return ref.replace(day=1)


def month_end(ref: date) -> date:
    if ref.month == 12:
        return date(ref.year + 1, 1, 1) - timedelta(days=1)
    return date(ref.year, ref.month + 1, 1) - timedelta(days=1)


def shift_ref_date(ref: date, view: str, direction: int) -> date:
    if view == "weekly":
        return ref + timedelta(weeks=direction)
    if view in ("monthly", "calendar"):
        month = ref.month + direction
        year = ref.year
        while month < 1:
            month += 12
            year -= 1
        while month > 12:
            month -= 12
            year += 1
        day = min(ref.day, month_end(date(year, month, 1)).day)
        return date(year, month, day)
    return ref + timedelta(days=direction)


def filter_plans_by_view(plans: list, view: str, ref: date) -> list:
    if view == "weekly":
        start, end = week_start(ref), week_end(ref)
        return [p for p in plans if start <= p.plan_date <= end]
    if view in ("monthly", "calendar"):
        start, end = month_start(ref), month_end(ref)
        return [p for p in plans if start <= p.plan_date <= end]
    return [p for p in plans if p.plan_date == ref]


def group_plans_by_date(plans: list) -> dict[date, list]:
    grouped: dict[date, list] = {}
    for plan in sorted(plans, key=lambda p: p.plan_date):
        grouped.setdefault(plan.plan_date, []).append(plan)
    return grouped


def build_month_grid(ref: date, plan_dates: set[date]) -> list[list[dict]]:
    weeks = monthcalendar(ref.year, ref.month)
    grid = []
    for week in weeks:
        row = []
        for day_num in week:
            if day_num == 0:
                row.append({"day": None, "date": None, "has_plans": False, "is_today": False, "is_ref": False})
            else:
                d = date(ref.year, ref.month, day_num)
                row.append({
                    "day": day_num,
                    "date": d,
                    "has_plans": d in plan_dates,
                    "is_today": d == date.today(),
                    "is_ref": d == ref,
                })
        grid.append(row)
    return grid


def period_label(view: str, ref: date) -> str:
    if view == "weekly":
        start, end = week_start(ref), week_end(ref)
        if start.month == end.month:
            return f"{start.strftime('%b %d')} – {end.strftime('%d, %Y')}"
        return f"{start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"
    if view in ("monthly", "calendar"):
        return ref.strftime("%B %Y")
    return ref.strftime("%A, %B %d, %Y")
