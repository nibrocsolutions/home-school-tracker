import re
from datetime import date
from io import BytesIO

from fpdf import FPDF

from app.activity_fields import parse_custom_fields
from app.calendar_utils import (
    group_plans_by_date,
    period_label,
)
from app.media_library import (
    activity_external_web_links,
    activity_media_urls,
    media_display_name,
)
from app.models import ActivityType, LessonPlan, SchoolDayType

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
    "red": (220, 38, 38),
}

ACTIVITY_TYPE_LABELS = {
    ActivityType.regular: "Regular",
    ActivityType.special: "Special Activity",
    ActivityType.subject: "Subject",
    ActivityType.history: "History",
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

    def _content_top_y(self) -> float:
        """Y position considered 'top of usable content' after a page break."""
        return self.t_margin + 2

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
        text_colors: list[tuple[int, int, int]] | None = None,
    ) -> None:
        if header:
            self.set_font("Helvetica", "B", 9)
            self.set_fill_color(*COLORS["primary"])
            default_text = COLORS["white"]
        else:
            self.set_font("Helvetica", "", 8)
            self.set_fill_color(*COLORS["row_alt"] if alt else COLORS["white"])
            default_text = COLORS["text"]

        safe_cells = [_safe_text(text) for text in cells]
        row_height = line_height
        for text, width in zip(safe_cells, widths):
            measured = self.multi_cell(
                width, line_height, text, dry_run=True, output="HEIGHT"
            )
            row_height = max(row_height, float(measured or line_height))

        # Keep the whole row on one page so tall teacher-note cells do not
        # page-break mid-row and leave large blank gaps on the next page.
        if self.get_y() + row_height > self.page_break_trigger:
            self.add_page()
            if header:
                self.set_font("Helvetica", "B", 9)
                self.set_fill_color(*COLORS["primary"])
            else:
                self.set_font("Helvetica", "", 8)
                self.set_fill_color(*COLORS["row_alt"] if alt else COLORS["white"])

        x_start = self.l_margin
        y_start = self.get_y()
        self.set_draw_color(*COLORS["border"])

        for index, (text, width) in enumerate(zip(safe_cells, widths)):
            color = default_text
            if text_colors and index < len(text_colors) and text_colors[index]:
                color = text_colors[index]
            self.set_text_color(*color)
            self.rect(x_start, y_start, width, row_height, style="DF")
            self.set_xy(x_start, y_start)
            self.multi_cell(width, line_height, text, border=0, fill=False, align="L")
            x_start += width

        self.set_text_color(*COLORS["text"])
        self.set_y(y_start + row_height)


def _normalize_pdf_text(text: str) -> str:
    """Collapse noisy textarea whitespace so PDF cells stay compact."""
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[^\S\n]+", " ", normalized)
    normalized = re.sub(r" *\n *", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _safe_text(text: str) -> str:
    return _normalize_pdf_text(text).encode("latin-1", errors="replace").decode("latin-1")


def _activity_completed(completions: dict[int, bool | dict] | None, activity_id: int) -> bool:
    if completions is None:
        return False
    value = completions.get(activity_id)
    if isinstance(value, dict):
        return bool(value.get("completed"))
    return bool(value)


def _completion_entry(
    completions: dict[int, bool | dict] | None, activity_id: int
) -> dict | None:
    if completions is None:
        return None
    value = completions.get(activity_id)
    if isinstance(value, dict):
        return value
    if value is None:
        return None
    return {"completed": bool(value), "student_message": None}


def _activity_type_label(activity) -> str:
    activity_type = getattr(activity, "activity_type", None)
    if isinstance(activity_type, ActivityType):
        return ACTIVITY_TYPE_LABELS.get(activity_type, activity_type.value)
    if activity_type:
        try:
            return ACTIVITY_TYPE_LABELS.get(ActivityType(activity_type), str(activity_type))
        except ValueError:
            return str(activity_type)
    return "Regular"


def _append_labeled_block(parts: list[str], label: str, body: str) -> None:
    text = _normalize_pdf_text(body)
    if not text:
        return
    parts.append(f"{label}:\n{text}")


def _activity_details_text(
    act,
    completions: dict[int, bool | dict] | None,
) -> str:
    """Build the full details cell for one activity, including all plan fields."""
    parts: list[str] = []

    description = _normalize_pdf_text(act.description or "")
    if description:
        parts.append(description)
    if not getattr(act, "is_required", True):
        parts.append("(optional)")

    activity_type = getattr(act, "activity_type", None)
    if activity_type and activity_type != ActivityType.regular:
        parts.append(f"Type: {_activity_type_label(act)}")

    _append_labeled_block(parts, "Teacher Notes", getattr(act, "teacher_notes", None) or "")

    custom_fields = parse_custom_fields(getattr(act, "custom_fields", None))
    for field_text in custom_fields:
        text = _normalize_pdf_text(field_text)
        if text:
            parts.append(text)

    media_urls = activity_media_urls(
        media_attachments=getattr(act, "media_attachments", None),
        external_link=getattr(act, "external_link", None),
        audio_url=getattr(act, "audio_url", None),
    )
    if media_urls:
        media_lines = [media_display_name(url) or url for url in media_urls]
        _append_labeled_block(parts, "Media", "\n".join(media_lines))

    web_links = activity_external_web_links(getattr(act, "external_link", None))
    if web_links:
        _append_labeled_block(parts, "Links", "\n".join(web_links))

    completion = _completion_entry(completions, act.id)
    student_notes = ""
    if completion:
        student_notes = _normalize_pdf_text(completion.get("student_message") or "")
    if student_notes:
        _append_labeled_block(parts, "Student Notes", student_notes)

    return "\n".join(parts) if parts else "-"


def _render_activity_table(
    pdf: LessonPlanPDF,
    plan: LessonPlan,
    completions: dict[int, bool | dict] | None,
) -> None:
    width = pdf._usable_width()
    show_status = completions is not None
    if show_status:
        widths = [width * 0.06, width * 0.24, width * 0.50, width * 0.20]
        headers = ["#", "Activity", "Details", "Status"]
    else:
        widths = [width * 0.06, width * 0.28, width * 0.66]
        headers = ["#", "Activity", "Details"]

    pdf._table_row(headers, widths, header=True)
    for idx, act in enumerate(sorted(plan.activities, key=lambda a: a.sort_order), start=1):
        desc = _activity_details_text(act, completions)
        cells = [str(idx), act.title, desc]
        if show_status:
            status = "Done" if _activity_completed(completions, act.id) else "Pending"
            cells.append(status)
        pdf._multi_line_table_row(cells, widths, alt=idx % 2 == 0)
    pdf.ln(4)


def _render_plan_block(
    pdf: LessonPlanPDF,
    plan: LessonPlan,
    completions: dict[int, bool | dict] | None,
    *,
    show_date: bool = True,
) -> None:
    pdf._section_title(plan.title)
    meta = []
    if show_date:
        meta.append(plan.plan_date.strftime("%A, %B %d, %Y"))
    if plan.student is not None:
        meta.append(f"Student: {plan.student.full_name}")
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


def _render_day_off_detail(pdf: LessonPlanPDF, day_off: date) -> None:
    """Render a day off like a normal day entry: date heading + short note."""
    pdf._section_title(day_off.strftime("%A, %B %d, %Y"))
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(*COLORS["red"])
    pdf.cell(0, 5, "No lesson plans scheduled (day off).", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*COLORS["text"])
    pdf.ln(4)


def _render_single_day(
    pdf: LessonPlanPDF,
    plan_date: date,
    day_plans: list[LessonPlan],
    completions_by_plan: dict[int, dict[int, bool]] | None,
    *,
    is_day_off: bool,
) -> None:
    if is_day_off:
        _render_day_off_detail(pdf, plan_date)
    for plan in day_plans:
        plan_completions = completions_by_plan.get(plan.id) if completions_by_plan else None
        _render_plan_block(pdf, plan, plan_completions, show_date=True)


def _render_day_without_splitting(
    pdf: LessonPlanPDF,
    plan_date: date,
    day_plans: list[LessonPlan],
    completions_by_plan: dict[int, dict[int, bool]] | None,
    *,
    is_day_off: bool,
) -> None:
    """Render one calendar day on a single page when it fits; never start mid-page if it won't."""
    start_y = pdf.get_y()
    start_page = pdf.page_no()

    with pdf.offset_rendering() as dummy:
        _render_single_day(
            dummy,
            plan_date,
            day_plans,
            completions_by_plan,
            is_day_off=is_day_off,
        )
        measured_pages = dummy.page_no()

    # Content needs more than the remaining space on this page.
    if measured_pages > start_page and start_y > pdf._content_top_y() + 8:
        pdf.add_page()

    _render_single_day(
        pdf,
        plan_date,
        day_plans,
        completions_by_plan,
        is_day_off=is_day_off,
    )


def _render_chronological_details(
    pdf: LessonPlanPDF,
    plans: list[LessonPlan],
    completions_by_plan: dict[int, dict[int, bool]] | None,
    days_off: list[date] | None = None,
) -> None:
    """Render lesson plans and day-off markers in date order, keeping each day together."""
    grouped = group_plans_by_date(plans)
    off_set = set(days_off or [])
    all_dates = sorted(set(grouped.keys()) | off_set)
    for plan_date in all_dates:
        _render_day_without_splitting(
            pdf,
            plan_date,
            grouped.get(plan_date, []),
            completions_by_plan,
            is_day_off=plan_date in off_set,
        )


def _render_daily_view(
    pdf: LessonPlanPDF,
    plans: list[LessonPlan],
    completions_by_plan: dict[int, dict[int, bool]] | None,
    days_off: list[date] | None = None,
) -> None:
    _render_chronological_details(pdf, plans, completions_by_plan, days_off=days_off)


def _render_weekly_view(
    pdf: LessonPlanPDF,
    plans: list[LessonPlan],
    completions_by_plan: dict[int, dict[int, bool]] | None,
    days_off: list[date] | None = None,
) -> None:
    # Weekly PDF shows the same chronological daily details as the daily/monthly
    # detail export — no weekly overview table.
    _render_chronological_details(pdf, plans, completions_by_plan, days_off=days_off)


def _render_monthly_view(
    pdf: LessonPlanPDF,
    plans: list[LessonPlan],
    ref: date,
    completions_by_plan: dict[int, dict[int, bool]] | None,
    days_off: list[date] | None = None,
) -> None:
    # Monthly details PDF: chronological daily lesson details for the month.
    _render_daily_view(pdf, plans, completions_by_plan, days_off=days_off)


def build_lesson_plan_pdf(
    plans: list[LessonPlan],
    view: str,
    ref: date,
    *,
    subtitle: str,
    completions_by_plan: dict[int, dict[int, bool]] | None = None,
    days_off: list[date] | None = None,
) -> bytes:
    pdf = LessonPlanPDF()
    pdf.add_page()

    title = period_label(view, ref)
    if view == "weekly":
        title = f"Daily Lesson Plans — {title}"
    elif view == "monthly":
        title = f"Daily Lesson Plans — {title}"

    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*COLORS["text"])
    pdf.cell(0, 8, _safe_text(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*COLORS["muted"])
    pdf.cell(0, 6, _safe_text(subtitle), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    off_list = list(days_off or [])

    if not plans and not off_list:
        pdf.set_font("Helvetica", "I", 11)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 8, "No lesson plans for this period.", new_x="LMARGIN", new_y="NEXT")
    elif view == "weekly":
        _render_weekly_view(pdf, plans, completions_by_plan, days_off=off_list)
    elif view == "monthly":
        _render_monthly_view(pdf, plans, ref, completions_by_plan, days_off=off_list)
    else:
        _render_daily_view(pdf, plans, completions_by_plan, days_off=off_list)

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


class AttendanceReportPDF(LessonPlanPDF):
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
            self.cell(0, 5, "Attendance Report", new_x="LMARGIN", new_y="NEXT")
            self.ln(6)


def _format_date_list(dates: list[date]) -> str:
    if not dates:
        return "None"
    return ", ".join(d.strftime("%b %d, %Y") for d in sorted(dates))


def _render_date_block(pdf: AttendanceReportPDF, title: str, body: str) -> None:
    pdf._section_title(title)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*COLORS["text"])
    pdf.multi_cell(pdf._usable_width(), 5, _safe_text(body), align="L")
    pdf.ln(4)


def build_attendance_report_pdf(attendance: dict, *, subtitle: str) -> bytes:
    pdf = AttendanceReportPDF()
    pdf.add_page()

    start = attendance["start_date"]
    end = attendance["end_date"]
    counts = attendance["counts"]

    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*COLORS["text"])
    pdf.cell(
        0,
        8,
        _safe_text(
            f"{start.strftime('%B %d, %Y')} - {end.strftime('%B %d, %Y')}"
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*COLORS["muted"])
    pdf.cell(0, 6, _safe_text(subtitle), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf._section_title("Summary")
    width = pdf._usable_width()
    summary_rows = [
        ("Possible School Days", str(counts["possible_days"])),
        ("School Days", str(counts["planned_actual_count"])),
        ("Days Off", str(counts["planned_school_off_count"])),
        ("Completed School Days", str(counts["completed_count"])),
        ("Required Full Days", str(attendance["required_days"])),
        ("School Days Remaining", str(attendance["remaining_days"])),
    ]
    label_width = width * 0.62
    value_width = width * 0.38
    pdf._table_row(["Metric", "Count"], [label_width, value_width], header=True)
    for index, (label, value) in enumerate(summary_rows):
        pdf._table_row([label, value], [label_width, value_width], alt=index % 2 == 1)
    pdf.ln(4)

    by_type = attendance["by_type"]
    _render_date_block(
        pdf,
        "Completed School Days",
        _format_date_list(attendance["completed_dates"]),
    )
    _render_date_block(
        pdf,
        "School Days (Not Completed)",
        _format_date_list(attendance["incomplete_actual_dates"]),
    )
    _render_date_block(
        pdf,
        "Days Off",
        _format_date_list(
            [entry["date"] for entry in by_type.get(SchoolDayType.school_off, [])]
            + [entry["date"] for entry in by_type.get(SchoolDayType.holiday, [])]
        ),
    )

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()


def attendance_report_pdf_filename(start: date, end: date) -> str:
    return f"attendance-report-{start.isoformat()}-to-{end.isoformat()}.pdf"
