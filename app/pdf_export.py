from datetime import date, timedelta
from io import BytesIO

from fpdf import FPDF

from app.calendar_utils import (
    build_month_grid,
    group_plans_by_date,
    month_end,
    month_start,
    period_label,
    week_start,
)
from app.models import LessonPlan

COLORS = {
    "primary": (79, 110, 247),
    "text": (45, 49, 66),
    "muted": (100, 100, 100),
    "header_bg": (237, 233, 254),
    "border": (200, 194, 217),
    "accent": (255, 140, 66),
    "green": (34, 197, 94),
    "pink": (244, 114, 182),
    "white": (255, 255, 255),
    "row_alt": (248, 246, 242),
}


class LessonPlanPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=18)

    def header(self):
        if self.page_no() == 1:
            self._draw_books_logo(self.l_margin, 8, 14)
            self.set_xy(self.l_margin + 18, 8)
            self.set_font("Helvetica", "B", 16)
            self.set_text_color(*COLORS["primary"])
            self.cell(0, 7, "Home School Tracker", new_x="LMARGIN", new_y="NEXT")
            self.set_x(self.l_margin + 18)
            self.set_font("Helvetica", "", 10)
            self.set_text_color(*COLORS["muted"])
            self.cell(0, 5, "Lesson Plan Report", new_x="LMARGIN", new_y="NEXT")
            self.ln(6)

    def footer(self):
        self.set_y(-14)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(
            0, 8,
            f"Generated {date.today().strftime('%B %d, %Y')}  |  Page {self.page_no()}",
            align="C",
        )

    def _draw_books_logo(self, x: float, y: float, size: float) -> None:
        self.set_fill_color(*COLORS["primary"])
        self.rect(x, y, size, size, style="F")
        self.set_fill_color(*COLORS["accent"])
        self.rect(x + 1.5, y + 3, size * 0.28, size - 4, style="F")
        self.set_fill_color(*COLORS["green"])
        self.rect(x + size * 0.35, y + 2.5, size * 0.28, size - 3.5, style="F")
        self.set_fill_color(*COLORS["pink"])
        self.rect(x + size * 0.62, y + 3.5, size * 0.28, size - 4.5, style="F")

    def _usable_width(self) -> float:
        return self.w - self.l_margin - self.r_margin

    def _section_title(self, text: str) -> None:
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(*COLORS["primary"])
        self.set_fill_color(*COLORS["header_bg"])
        self.cell(self._usable_width(), 8, _safe_text(text), border=0, fill=True, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def _table_row(self, cells: list[str], widths: list[float], *, header: bool = False, alt: bool = False) -> None:
        if header:
            self.set_font("Helvetica", "B", 9)
            self.set_fill_color(*COLORS["primary"])
            self.set_text_color(*COLORS["white"])
        else:
            self.set_font("Helvetica", "", 9)
            self.set_fill_color(*COLORS["row_alt"] if alt else COLORS["white"])
            self.set_text_color(*COLORS["text"])

        row_height = 7
        x_start = self.l_margin
        self.set_x(x_start)

        for text, width in zip(cells, widths):
            self.cell(width, row_height, _safe_text(text), border=1, fill=True)

        self.ln(row_height)

    def _multi_line_table_row(
        self,
        cells: list[str],
        widths: list[float],
        *,
        header: bool = False,
        alt: bool = False,
        line_height: float = 5,
    ) -> None:
        if header:
            self.set_font("Helvetica", "B", 9)
            self.set_fill_color(*COLORS["primary"])
            self.set_text_color(*COLORS["white"])
        else:
            self.set_font("Helvetica", "", 8)
            self.set_fill_color(*COLORS["row_alt"] if alt else COLORS["white"])
            self.set_text_color(*COLORS["text"])

        x_start = self.l_margin
        y_start = self.get_y()
        max_height = line_height

        for text, width in zip(cells, widths):
            self.set_xy(x_start, y_start)
            self.multi_cell(width, line_height, _safe_text(text), border=1, fill=True, align="L")
            cell_height = self.get_y() - y_start
            max_height = max(max_height, cell_height)
            x_start += width

        self.set_y(y_start + max_height)


def _safe_text(text: str) -> str:
    return str(text).encode("latin-1", errors="replace").decode("latin-1")


def _status_label(activity_id: int, completions: dict[int, bool] | None) -> str:
    if completions is None:
        return "Required" if True else ""
    return "Done" if completions.get(activity_id) else "Pending"


def _activities_summary(activities: list) -> str:
    titles = [a.title for a in sorted(activities, key=lambda a: a.sort_order)]
    if not titles:
        return "-"
    if len(titles) <= 2:
        return "; ".join(titles)
    return f"{titles[0]}; {titles[1]} (+{len(titles) - 2} more)"


def _render_activity_table(
    pdf: LessonPlanPDF,
    plan: LessonPlan,
    completions: dict[int, bool] | None,
) -> None:
    width = pdf._usable_width()
    show_status = completions is not None
    if show_status:
        widths = [width * 0.06, width * 0.28, width * 0.46, width * 0.20]
        headers = ["#", "Activity", "Description", "Status"]
    else:
        widths = [width * 0.06, width * 0.34, width * 0.60]
        headers = ["#", "Activity", "Description"]

    pdf._table_row(headers, widths, header=True)
    for idx, act in enumerate(sorted(plan.activities, key=lambda a: a.sort_order), start=1):
        desc = act.description or "-"
        if not act.is_required:
            desc = f"{desc} (optional)" if desc != "-" else "(optional)"
        cells = [str(idx), act.title, desc]
        if show_status:
            status = "Done" if completions.get(act.id) else "Pending"
            cells.append(status)
        pdf._multi_line_table_row(cells, widths, alt=idx % 2 == 0)
    pdf.ln(4)


def _render_plan_block(
    pdf: LessonPlanPDF,
    plan: LessonPlan,
    completions: dict[int, bool] | None,
    *,
    show_date: bool = True,
) -> None:
    pdf._section_title(plan.title)
    meta = []
    if show_date:
        meta.append(plan.plan_date.strftime("%A, %B %d, %Y"))
    if hasattr(plan, "student") and plan.student:
        meta.append(f"Student: {plan.student.full_name}")
    if hasattr(plan, "teacher") and plan.teacher:
        meta.append(f"Teacher: {plan.teacher.full_name}")
    if meta:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*COLORS["muted"])
        pdf.cell(0, 5, _safe_text("  |  ".join(meta)), new_x="LMARGIN", new_y="NEXT")
    if plan.description:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(80, 80, 80)
        pdf.multi_cell(pdf._usable_width(), 5, _safe_text(plan.description))
    pdf.ln(2)
    _render_activity_table(pdf, plan, completions)


def _render_weekly_overview_table(pdf: LessonPlanPDF, plans: list[LessonPlan]) -> None:
    pdf._section_title("Weekly Overview")
    width = pdf._usable_width()
    widths = [width * 0.14, width * 0.10, width * 0.18, width * 0.28, width * 0.30]
    pdf._table_row(["Date", "Day", "Student", "Lesson Plan", "Activities"], widths, header=True)

    grouped = group_plans_by_date(plans)
    row_idx = 0
    for plan_date, day_plans in sorted(grouped.items()):
        for plan in day_plans:
            student_name = plan.student.full_name if plan.student else "-"
            pdf._multi_line_table_row(
                [
                    plan_date.strftime("%b %d"),
                    plan_date.strftime("%a"),
                    student_name,
                    plan.title,
                    _activities_summary(plan.activities),
                ],
                widths,
                alt=row_idx % 2 == 0,
            )
            row_idx += 1
    pdf.ln(6)


def _render_monthly_overview_table(pdf: LessonPlanPDF, plans: list[LessonPlan], ref: date) -> None:
    pdf._section_title(f"Monthly Calendar — {ref.strftime('%B %Y')}")
    plan_by_date = group_plans_by_date(plans)
    plan_dates = set(plan_by_date.keys())
    grid = build_month_grid(ref, plan_dates)

    width = pdf._usable_width()
    day_width = width / 7
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    pdf._table_row(weekdays, [day_width] * 7, header=True)

    for week in grid:
        cells = []
        for cell in week:
            if cell["day"] is None:
                cells.append("")
            else:
                d = cell["date"]
                day_plans = plan_by_date.get(d, [])
                if day_plans:
                    titles = ", ".join(p.title for p in day_plans[:2])
                    if len(day_plans) > 2:
                        titles += f" (+{len(day_plans) - 2})"
                    cells.append(f"{cell['day']}\n{titles}")
                else:
                    cells.append(str(cell["day"]))
        pdf._multi_line_table_row(cells, [day_width] * 7, line_height=6)
    pdf.ln(6)


def _render_daily_view(
    pdf: LessonPlanPDF,
    plans: list[LessonPlan],
    completions_by_plan: dict[int, dict[int, bool]] | None,
) -> None:
    grouped = group_plans_by_date(plans)
    for _, day_plans in sorted(grouped.items()):
        for plan in day_plans:
            plan_completions = completions_by_plan.get(plan.id) if completions_by_plan else None
            _render_plan_block(pdf, plan, plan_completions, show_date=True)


def _render_weekly_view(
    pdf: LessonPlanPDF,
    plans: list[LessonPlan],
    completions_by_plan: dict[int, dict[int, bool]] | None,
) -> None:
    _render_weekly_overview_table(pdf, plans)
    pdf._section_title("Lesson Plan Details")
    grouped = group_plans_by_date(plans)
    for plan_date, day_plans in sorted(grouped.items()):
        for plan in day_plans:
            plan_completions = completions_by_plan.get(plan.id) if completions_by_plan else None
            _render_plan_block(pdf, plan, plan_completions, show_date=True)


def _render_monthly_view(
    pdf: LessonPlanPDF,
    plans: list[LessonPlan],
    ref: date,
    completions_by_plan: dict[int, dict[int, bool]] | None,
) -> None:
    _render_monthly_overview_table(pdf, plans, ref)
    pdf._section_title("Lesson Plan Details")
    grouped = group_plans_by_date(plans)
    for plan_date, day_plans in sorted(grouped.items()):
        for plan in day_plans:
            plan_completions = completions_by_plan.get(plan.id) if completions_by_plan else None
            _render_plan_block(pdf, plan, plan_completions, show_date=True)


def build_lesson_plan_pdf(
    plans: list[LessonPlan],
    view: str,
    ref: date,
    *,
    subtitle: str,
    completions_by_plan: dict[int, dict[int, bool]] | None = None,
) -> bytes:
    pdf = LessonPlanPDF()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*COLORS["text"])
    pdf.cell(0, 8, _safe_text(period_label(view, ref)), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*COLORS["muted"])
    pdf.cell(0, 6, _safe_text(subtitle), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    if not plans:
        pdf.set_font("Helvetica", "I", 11)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 8, "No lesson plans for this period.", new_x="LMARGIN", new_y="NEXT")
    elif view == "weekly":
        _render_weekly_view(pdf, plans, completions_by_plan)
    elif view == "monthly":
        _render_monthly_view(pdf, plans, ref, completions_by_plan)
    else:
        _render_daily_view(pdf, plans, completions_by_plan)

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()


def pdf_filename(view: str, ref: date, role: str) -> str:
    if view == "monthly":
        slug = ref.strftime("%Y-%m")
    elif view == "weekly":
        slug = f"week-{ref.isoformat()}"
    else:
        slug = ref.isoformat()
    return f"lesson-plans-{role}-{view}-{slug}.pdf"


def pdf_response_headers(filename: str, inline: bool) -> dict[str, str]:
    disposition = "inline" if inline else "attachment"
    return {
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        "Content-Type": "application/pdf",
    }
