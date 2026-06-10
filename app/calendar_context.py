from datetime import date, timedelta

from app.calendar_utils import (
    build_month_grid,
    filter_plans_by_view,
    group_plans_by_date,
    month_end,
    month_start,
    parse_ref_date,
    period_label,
    shift_ref_date,
    week_start,
)


def build_calendar_context(plans: list, view: str, ref_date: str | None) -> dict:
    ref = parse_ref_date(ref_date)
    lesson_plans = filter_plans_by_view(plans, view, ref)
    grouped_plans = group_plans_by_date(lesson_plans)
    sorted_grouped_plans = sorted(grouped_plans.items(), key=lambda item: item[0])

    week_days = []
    if view == "weekly":
        start = week_start(ref)
        for i in range(7):
            d = start + timedelta(days=i)
            week_days.append({
                "date": d,
                "label": d.strftime("%a"),
                "day_num": d.day,
                "is_today": d == date.today(),
                "is_ref": d == ref,
                "plans": grouped_plans.get(d, []),
            })

    month_grid = []
    if view == "monthly":
        month_plan_dates = {p.plan_date for p in plans if month_start(ref) <= p.plan_date <= month_end(ref)}
        month_grid = build_month_grid(ref, month_plan_dates)

    return {
        "lesson_plans": lesson_plans,
        "grouped_plans": grouped_plans,
        "sorted_grouped_plans": sorted_grouped_plans,
        "view": view,
        "ref_date": ref.isoformat(),
        "ref": ref,
        "period_label": period_label(view, ref),
        "prev_ref": shift_ref_date(ref, view, -1).isoformat(),
        "next_ref": shift_ref_date(ref, view, 1).isoformat(),
        "week_days": week_days,
        "month_grid": month_grid,
    }
