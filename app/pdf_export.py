from datetime import date
from io import BytesIO

from fpdf import FPDF

from app.calendar_utils import group_plans_by_date, period_label
from app.models import LessonPlan


class LessonPlanPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 18)
        self.set_text_color(79, 110, 247)
        self.cell(0, 10, "Home School Tracker", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 11)
        self.set_text_color(100, 100, 100)
        self.cell(0, 6, "Lesson Plan Report", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Generated {date.today().strftime('%B %d, %Y')}  |  Page {self.page_no()}", align="C")


def _safe_text(text: str) -> str:
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _activity_lines(activities: list, completions: dict[int, bool] | None = None) -> list[str]:
    lines = []
    for act in sorted(activities, key=lambda a: a.sort_order):
        prefix = "[ ]"
        if completions is not None:
            prefix = "[x]" if completions.get(act.id) else "[ ]"
        optional = " (optional)" if not act.is_required else ""
        lines.append(f"  {prefix} {act.title}{optional}")
        if act.description:
            lines.append(f"       {_safe_text(act.description)}")
    return lines


def build_lesson_plan_pdf(
    plans: list[LessonPlan],
    view: str,
    ref: date,
    *,
    subtitle: str,
    completions_by_plan: dict[int, dict[int, bool]] | None = None,
) -> bytes:
    pdf = LessonPlanPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(45, 49, 66)
    pdf.cell(0, 8, _safe_text(period_label(view, ref)), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, _safe_text(subtitle), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    if not plans:
        pdf.set_font("Helvetica", "I", 11)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 8, "No lesson plans for this period.", new_x="LMARGIN", new_y="NEXT")
    else:
        grouped = group_plans_by_date(plans)
        for plan_date, day_plans in sorted(grouped.items()):
            if view != "daily":
                pdf.set_fill_color(237, 233, 254)
                pdf.set_font("Helvetica", "B", 11)
                pdf.set_text_color(79, 110, 247)
                pdf.cell(
                    0, 8,
                    plan_date.strftime("%A, %B %d, %Y"),
                    new_x="LMARGIN", new_y="NEXT",
                    fill=True,
                )
                pdf.ln(2)

            for plan in day_plans:
                content_width = pdf.w - pdf.l_margin - pdf.r_margin
                pdf.set_font("Helvetica", "B", 12)
                pdf.set_text_color(45, 49, 66)
                pdf.cell(0, 7, _safe_text(plan.title), new_x="LMARGIN", new_y="NEXT")

                meta_parts = []
                if hasattr(plan, "student") and plan.student:
                    meta_parts.append(f"Student: {plan.student.full_name}")
                if hasattr(plan, "teacher") and plan.teacher:
                    meta_parts.append(f"Teacher: {plan.teacher.full_name}")
                if view == "daily":
                    meta_parts.insert(0, plan.plan_date.strftime("%A, %B %d, %Y"))
                if meta_parts:
                    pdf.set_font("Helvetica", "", 9)
                    pdf.set_text_color(100, 100, 100)
                    pdf.cell(0, 5, _safe_text("  |  ".join(meta_parts)), new_x="LMARGIN", new_y="NEXT")

                if plan.description:
                    pdf.set_font("Helvetica", "I", 10)
                    pdf.set_text_color(80, 80, 80)
                    pdf.set_x(pdf.l_margin)
                    pdf.multi_cell(content_width, 5, _safe_text(plan.description))
                    pdf.ln(1)

                plan_completions = completions_by_plan.get(plan.id) if completions_by_plan else None
                pdf.set_font("Helvetica", "", 10)
                pdf.set_text_color(45, 49, 66)
                for line in _activity_lines(plan.activities, plan_completions):
                    pdf.set_x(pdf.l_margin)
                    pdf.multi_cell(content_width, 5, _safe_text(line))

                pdf.ln(4)
                pdf.set_draw_color(230, 226, 217)
                y = pdf.get_y()
                pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
                pdf.ln(6)

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
