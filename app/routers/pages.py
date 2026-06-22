import json
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response as RawResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.app_settings import get_app_settings, sample_data_enabled, sample_lesson_plans_enabled
from app.auth import (
    ROLE_HOME_PAGES,
    authenticate_user,
    create_access_token,
    hash_password,
    require_roles,
)
from app.backup import export_database, import_database
from app.calendar_context import build_calendar_context
from app.database import get_db
from app.models import (
    Activity,
    ActivityCompletion,
    ActivityType,
    LessonPlan,
    PlannedSchoolDay,
    ScheduleItemKind,
    SchoolDayType,
    SchoolDayYear,
    SpecialActivityKind,
    User,
    UserRole,
    WeeklyScheduleItem,
)
from app.lesson_plan_generator import populate_lesson_plans_from_subjects
from app.lesson_planning_context import build_lesson_planning_context
from app.sample_plans import SAMPLE_LESSON_PLANS
from app.school_day_context import build_school_day_context
from app.school_year_utils import (
    collect_school_day_attendance,
    count_possible_school_days,
    ensure_planned_days,
    holiday_name_for_date,
    planned_day_counts,
)
from app.pdf_export import (
    attendance_report_pdf_filename,
    build_attendance_report_pdf,
    build_lesson_plan_pdf,
    pdf_filename,
    pdf_response_headers,
)
from app.weekly_schedule import (
    WEEKDAY_LABELS,
    format_weekdays,
    schedule_item_to_activity,
    schedule_items_for_date,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def render(request: Request, name: str, context: dict, status_code: int = 200):
    base = {"request": request, "app_name": "Home School Tracker"}
    base.update(context)
    return templates.TemplateResponse(name, base, status_code=status_code)


def load_completions_for_plans(
    db: Session, student_id: int, plans: list[LessonPlan]
) -> dict[int, dict[int, dict]]:
    result: dict[int, dict[int, dict]] = {}
    for plan in plans:
        activity_map: dict[int, dict] = {}
        for activity in plan.activities:
            completion = (
                db.query(ActivityCompletion)
                .filter(
                    ActivityCompletion.activity_id == activity.id,
                    ActivityCompletion.student_id == student_id,
                )
                .first()
            )
            activity_map[activity.id] = {
                "completed": completion.completed if completion else False,
                "student_message": completion.student_message if completion else None,
            }
        result[plan.id] = activity_map
    return result


def _fetch_student_responses(db: Session, teacher_id: int) -> list[dict]:
    rows = (
        db.query(ActivityCompletion, Activity, LessonPlan, User)
        .join(Activity, ActivityCompletion.activity_id == Activity.id)
        .join(LessonPlan, Activity.lesson_plan_id == LessonPlan.id)
        .join(User, ActivityCompletion.student_id == User.id)
        .filter(
            LessonPlan.teacher_id == teacher_id,
            ActivityCompletion.student_message.isnot(None),
            ActivityCompletion.student_message != "",
        )
        .order_by(ActivityCompletion.completed_at.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "student_name": student.full_name,
            "activity_title": activity.title,
            "plan_title": plan.title,
            "plan_date": plan.plan_date,
            "message": completion.student_message,
            "completed_at": completion.completed_at,
        }
        for completion, activity, plan, student in rows
    ]


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    return render(
        request,
        "login.html",
        {"show_sample_data": sample_data_enabled(db)},
    )


@router.post("/login")
async def login(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    username: str = Form(...),
    password: str = Form(...),
):
    user = authenticate_user(db, username, password)
    if not user:
        return RedirectResponse(url="/?error=invalid", status_code=status.HTTP_303_SEE_OTHER)

    token = create_access_token(user.id, user.role)
    redirect = RedirectResponse(url=ROLE_HOME_PAGES[user.role], status_code=status.HTTP_303_SEE_OTHER)
    redirect.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=60 * 60 * 12,
        samesite="lax",
    )
    return redirect


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
):
    users = db.query(User).order_by(User.role, User.last_name).all()
    stats = {
        "total_users": len(users),
        "active_users": sum(1 for u in users if u.is_active),
        "lesson_plans": db.query(LessonPlan).count(),
        "activities_today": db.query(Activity)
        .join(LessonPlan)
        .filter(LessonPlan.plan_date == date.today())
        .count(),
    }
    return render(
        request,
        "admin/dashboard.html",
        {"user": current_user, "users": users, "stats": stats},
    )


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
):
    admins = db.query(User).filter(User.role == UserRole.admin).all()
    teachers = db.query(User).filter(User.role == UserRole.teacher).all()
    students = db.query(User).filter(User.role == UserRole.student).all()
    return render(
        request,
        "admin/users.html",
        {
            "user": current_user,
            "admins": admins,
            "teachers": teachers,
            "students": students,
        },
    )


@router.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
):
    settings = get_app_settings(db)
    return render(
        request,
        "admin/settings.html",
        {"user": current_user, "settings": settings},
    )


@router.post("/admin/settings")
async def save_admin_settings(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
    sample_lesson_plans_enabled: str | None = Form(None),
    sample_data_enabled: str | None = Form(None),
):
    settings = get_app_settings(db)
    settings.sample_lesson_plans_enabled = sample_lesson_plans_enabled == "on"
    settings.sample_data_enabled = sample_data_enabled == "on"
    settings.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(
        url="/admin/settings?success=saved",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/users")
async def create_user(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    role: str = Form(...),
    age: str = Form(""),
    grade: str = Form(""),
):
    if db.query(User).filter((User.username == username) | (User.email == email)).first():
        return RedirectResponse(
            url="/admin/users?error=exists",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    try:
        user_role = UserRole(role)
    except ValueError:
        return RedirectResponse(
            url="/admin/users?error=role",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    parsed_age = None
    if age.strip().isdigit():
        parsed_age = int(age.strip())

    new_user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        role=user_role,
        first_name=first_name,
        last_name=last_name,
        age=parsed_age if user_role == UserRole.student else None,
        grade=grade.strip() or None if user_role == UserRole.student else None,
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse(url="/admin/users?success=created", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/users/{user_id}/edit", response_class=HTMLResponse)
async def edit_user_page(
    user_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
):
    edit_user = db.query(User).filter(User.id == user_id).first()
    if not edit_user:
        raise HTTPException(status_code=404, detail="User not found")
    return render(
        request,
        "admin/user_edit.html",
        {"user": current_user, "edit_user": edit_user},
    )


@router.post("/admin/users/{user_id}/edit")
async def update_user(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(""),
    first_name: str = Form(...),
    last_name: str = Form(...),
    role: str = Form(...),
    age: str = Form(""),
    grade: str = Form(""),
):
    edit_user = db.query(User).filter(User.id == user_id).first()
    if not edit_user:
        raise HTTPException(status_code=404, detail="User not found")

    if password and len(password) < 6:
        return RedirectResponse(
            url=f"/admin/users/{user_id}/edit?error=password",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    duplicate = (
        db.query(User)
        .filter(
            User.id != user_id,
            (User.username == username) | (User.email == email),
        )
        .first()
    )
    if duplicate:
        return RedirectResponse(
            url=f"/admin/users/{user_id}/edit?error=exists",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        user_role = UserRole(role)
    except ValueError:
        return RedirectResponse(
            url=f"/admin/users/{user_id}/edit?error=role",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if edit_user.id != current_user.id:
        edit_user.role = user_role

    parsed_age = None
    if age.strip().isdigit():
        parsed_age = int(age.strip())

    edit_user.username = username
    edit_user.email = email
    edit_user.first_name = first_name
    edit_user.last_name = last_name
    if password:
        edit_user.password_hash = hash_password(password)
    if user_role == UserRole.student:
        edit_user.age = parsed_age
        edit_user.grade = grade.strip() or None
    else:
        edit_user.age = None
        edit_user.grade = None

    db.commit()
    return RedirectResponse(
        url=f"/admin/users/{user_id}/edit?success=updated",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/users/{user_id}/toggle")
async def toggle_user(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        return RedirectResponse(
            url="/admin/users?error=self",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    user.is_active = not user.is_active
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/backup", response_class=HTMLResponse)
async def admin_backup_page(
    request: Request,
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
):
    return render(request, "admin/backup.html", {"user": current_user})


@router.get("/admin/backup/export")
async def admin_backup_export(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
):
    backup_bytes = export_database(db)
    filename = f"hst-backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.json"
    return RawResponse(
        content=backup_bytes,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/admin/backup/import")
async def admin_backup_import(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
    backup_file: UploadFile = File(...),
):
    raw = await backup_file.read()
    try:
        import_database(db, raw)
    except ValueError:
        return RedirectResponse(
            url="/admin/backup?error=invalid",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(
        url="/admin/backup?success=imported",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/administrator")
async def administrator_redirect():
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_301_MOVED_PERMANENTLY)


def _visible_lesson_plans(db: Session, plans: list[LessonPlan]) -> list[LessonPlan]:
    if sample_data_enabled(db):
        return plans
    return [plan for plan in plans if not plan.is_sample_data]


def _fetch_teacher_plans(db: Session, teacher_id: int) -> list[LessonPlan]:
    plans = (
        db.query(LessonPlan)
        .options(joinedload(LessonPlan.activities), joinedload(LessonPlan.student))
        .filter(LessonPlan.teacher_id == teacher_id)
        .order_by(LessonPlan.plan_date.desc())
        .all()
    )
    return _visible_lesson_plans(db, plans)


def _fetch_school_day_year(db: Session, teacher_id: int) -> SchoolDayYear | None:
    return (
        db.query(SchoolDayYear)
        .options(joinedload(SchoolDayYear.planned_days))
        .filter(SchoolDayYear.teacher_id == teacher_id)
        .first()
    )


def _school_days_redirect(
    cal_month: str | None = None,
    success: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    params: list[str] = []
    if cal_month:
        params.append(f"cal_month={cal_month}")
    if success:
        params.append(f"success={success}")
    if error:
        params.append(f"error={error}")
    query = f"?{'&'.join(params)}" if params else ""
    return RedirectResponse(
        url=f"/teacher/school-days{query}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _fetch_active_students(db: Session) -> list[User]:
    return db.query(User).filter(User.role == UserRole.student, User.is_active == True).all()


def _fetch_weekly_schedule(db: Session, teacher_id: int) -> list[WeeklyScheduleItem]:
    return (
        db.query(WeeklyScheduleItem)
        .filter(WeeklyScheduleItem.teacher_id == teacher_id)
        .order_by(WeeklyScheduleItem.sort_order, WeeklyScheduleItem.id)
        .all()
    )


def _weekly_schedule_context(db: Session, teacher_id: int) -> dict:
    weekly_schedule = _fetch_weekly_schedule(db, teacher_id)
    return {
        "weekly_schedule": weekly_schedule,
        "weekday_labels": WEEKDAY_LABELS,
        "format_weekdays": format_weekdays,
        "weekly_schedule_meta_json": json.dumps(
            [
                {
                    "id": item.id,
                    "name": item.name,
                    "weekdays": item.weekdays,
                    "item_kind": item.item_kind.value,
                }
                for item in weekly_schedule
            ]
        ),
    }


def _lesson_planning_redirect(
    cal_month: str | None = None,
    plan_date: str | None = None,
    success: str | None = None,
    error: str | None = None,
    count: str | None = None,
) -> RedirectResponse:
    params: list[str] = []
    if cal_month:
        params.append(f"cal_month={cal_month}")
    if plan_date:
        params.append(f"plan_date={plan_date}")
    if success:
        params.append(f"success={success}")
    if error:
        params.append(f"error={error}")
    if count:
        params.append(f"count={count}")
    query = f"?{'&'.join(params)}" if params else ""
    return RedirectResponse(
        url=f"/teacher/lesson-planning{query}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _parse_lesson_activities(
    activity_titles: list[str],
    activity_descriptions: list[str],
    activity_types: list[str],
    activity_audio_urls: list[str],
    activity_external_links: list[str],
) -> list[tuple[str, str | None, ActivityType, str | None, str | None, int]]:
    activities_data = []
    for idx, act_title in enumerate(activity_titles):
        if not act_title.strip():
            continue
        desc = activity_descriptions[idx] if idx < len(activity_descriptions) else ""
        type_raw = activity_types[idx] if idx < len(activity_types) else "regular"
        audio = activity_audio_urls[idx] if idx < len(activity_audio_urls) else ""
        link = activity_external_links[idx] if idx < len(activity_external_links) else ""
        try:
            act_type = ActivityType(type_raw)
        except ValueError:
            act_type = ActivityType.regular
        activities_data.append(
            (
                act_title.strip(),
                desc.strip() or None,
                act_type,
                audio.strip() or None,
                link.strip() or None,
                idx + 1,
            )
        )
    return activities_data


def _save_lesson_plans_for_date(
    db: Session,
    teacher_id: int,
    parsed_date: date,
    title: str,
    description: str,
    student_ids: list[int],
    activities_data: list[tuple[str, str | None, ActivityType, str | None, str | None, int]],
) -> int:
    existing = (
        db.query(LessonPlan)
        .filter(LessonPlan.teacher_id == teacher_id, LessonPlan.plan_date == parsed_date)
        .all()
    )
    for plan in existing:
        db.delete(plan)

    for student_id in student_ids:
        plan = LessonPlan(
            title=title,
            description=description or None,
            plan_date=parsed_date,
            teacher_id=teacher_id,
            student_id=student_id,
        )
        db.add(plan)
        db.flush()
        for act_title, act_desc, act_type, audio, link, sort_order in activities_data:
            db.add(
                Activity(
                    lesson_plan_id=plan.id,
                    title=act_title,
                    description=act_desc,
                    sort_order=sort_order,
                    activity_type=act_type,
                    audio_url=audio,
                    external_link=link,
                )
            )
    return len(student_ids)


def _yearly_subjects_context(db: Session, teacher_id: int) -> dict:
    yearly_subjects = _fetch_weekly_schedule(db, teacher_id)
    return {
        "yearly_subjects": yearly_subjects,
        "weekday_labels": WEEKDAY_LABELS,
        "format_weekdays": format_weekdays,
    }


def _sample_plans_context(db: Session) -> dict:
    show_samples = sample_lesson_plans_enabled(db) and sample_data_enabled(db)
    return {
        "show_sample_plans": show_samples,
        "sample_lesson_plans": SAMPLE_LESSON_PLANS if show_samples else [],
    }


def _legacy_teacher_redirect(
    tab: str | None,
    cal_month: str | None = None,
    view: str | None = None,
    ref_date: str | None = None,
) -> RedirectResponse | None:
    if tab == "school-days":
        params: list[str] = []
        if cal_month:
            params.append(f"cal_month={cal_month}")
        query = f"?{'&'.join(params)}" if params else ""
        return RedirectResponse(url=f"/teacher/school-days{query}", status_code=status.HTTP_303_SEE_OTHER)
    if tab == "lessons":
        params = []
        if ref_date:
            params.append(f"plan_date={ref_date}")
            params.append(f"cal_month={ref_date[:7]}")
        query = f"?{'&'.join(params)}" if params else ""
        return RedirectResponse(url=f"/teacher/lesson-planning{query}", status_code=status.HTTP_303_SEE_OTHER)
    return None


@router.get("/teacher", response_class=HTMLResponse)
async def teacher_hub(
    tab: str | None = Query(None),
    cal_month: str | None = Query(None),
    view: str | None = Query(None),
    ref_date: str | None = Query(None),
    success: str | None = Query(None),
    error: str | None = Query(None),
    count: str | None = Query(None),
):
    if redirect := _legacy_teacher_redirect(tab, cal_month, view, ref_date):
        return redirect

    params: list[str] = []
    if cal_month:
        params.append(f"cal_month={cal_month}")
    if ref_date:
        params.append(f"plan_date={ref_date}")
        if not cal_month:
            params.append(f"cal_month={ref_date[:7]}")
    if success:
        params.append(f"success={success}")
    if error:
        params.append(f"error={error}")
    if count:
        params.append(f"count={count}")
    query = f"?{'&'.join(params)}" if params else ""
    return RedirectResponse(url=f"/teacher/lesson-planning{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/teacher/lesson-planning", response_class=HTMLResponse)
async def teacher_lesson_planning_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.teacher))],
    cal_month: str | None = Query(None),
    plan_date: str | None = Query(None),
):
    school_year = _fetch_school_day_year(db, current_user.id)
    if school_year:
        ensure_planned_days(db, school_year)
        db.commit()
        school_year = _fetch_school_day_year(db, current_user.id)

    all_plans = _fetch_teacher_plans(db, current_user.id)
    planning = build_lesson_planning_context(school_year, all_plans, cal_month, plan_date)
    students = _fetch_active_students(db)

    return render(
        request,
        "teacher/lesson_planning.html",
        {
            "user": current_user,
            "active_page": "lesson-planning",
            "students": students,
            **_yearly_subjects_context(db, current_user.id),
            **_sample_plans_context(db),
            **planning,
        },
    )


@router.get("/teacher/lesson-plans", response_class=HTMLResponse)
async def teacher_lesson_plans(
    view: str = Query("daily"),
    ref_date: str | None = Query(None),
    success: str | None = Query(None),
    error: str | None = Query(None),
    count: str | None = Query(None),
):
    params: list[str] = []
    if view == "monthly" and ref_date:
        params.append(f"cal_month={ref_date[:7]}")
        params.append(f"plan_date={ref_date}")
    elif ref_date:
        params.append(f"plan_date={ref_date}")
        params.append(f"cal_month={ref_date[:7]}")
    if success:
        params.append(f"success={success}")
    if error:
        params.append(f"error={error}")
    if count:
        params.append(f"count={count}")
    query = f"?{'&'.join(params)}" if params else ""
    return RedirectResponse(url=f"/teacher/lesson-planning{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/teacher/lesson-plans/new", response_class=HTMLResponse)
async def teacher_lesson_plan_new(
    plan_date: str | None = Query(None),
):
    params: list[str] = []
    if plan_date:
        params.append(f"plan_date={plan_date}")
        params.append(f"cal_month={plan_date[:7]}")
    query = f"?{'&'.join(params)}" if params else ""
    return RedirectResponse(url=f"/teacher/lesson-planning{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/teacher/weekly-schedule", response_class=HTMLResponse)
async def teacher_weekly_schedule_page(
    success: str | None = Query(None),
):
    query = f"?success={success}#yearly-subjects" if success else "#yearly-subjects"
    return RedirectResponse(url=f"/teacher/lesson-planning{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/teacher/lesson-planning/plan")
async def save_lesson_planning_plan(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.teacher))],
    title: str = Form(...),
    description: str = Form(""),
    plan_date: str = Form(...),
    cal_month: str = Form(""),
    student_ids: list[int] = Form(...),
    activity_titles: list[str] = Form(...),
    activity_descriptions: list[str] = Form(default=[]),
    activity_types: list[str] = Form(default=[]),
    activity_audio_urls: list[str] = Form(default=[]),
    activity_external_links: list[str] = Form(default=[]),
):
    school_year = _fetch_school_day_year(db, current_user.id)
    if school_year is None:
        return _lesson_planning_redirect(error="school-year")

    if not student_ids:
        return _lesson_planning_redirect(
            cal_month=cal_month or None,
            plan_date=plan_date,
            error="students",
        )

    try:
        parsed_date = date.fromisoformat(plan_date)
    except ValueError:
        return _lesson_planning_redirect(cal_month=cal_month or None, error="date")

    if not (school_year.start_date <= parsed_date <= school_year.end_date):
        return _lesson_planning_redirect(
            cal_month=cal_month or None,
            plan_date=plan_date,
            error="range",
        )

    activities_data = _parse_lesson_activities(
        activity_titles,
        activity_descriptions,
        activity_types,
        activity_audio_urls,
        activity_external_links,
    )
    count = _save_lesson_plans_for_date(
        db,
        current_user.id,
        parsed_date,
        title,
        description,
        student_ids,
        activities_data,
    )
    db.commit()
    return _lesson_planning_redirect(
        cal_month=cal_month or parsed_date.strftime("%Y-%m"),
        plan_date=plan_date,
        success="plan",
        count=str(count),
    )


@router.post("/teacher/lesson-planning/yearly-subjects")
async def save_yearly_subjects(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.teacher))],
    cal_month: str = Form(""),
    item_names: list[str] = Form(default=[]),
    item_kinds: list[str] = Form(default=[]),
    special_types: list[str] = Form(default=[]),
    weekdays_list: list[str] = Form(default=[]),
    lesson_amounts: list[str] = Form(default=[]),
    item_descriptions: list[str] = Form(default=[]),
    external_links: list[str] = Form(default=[]),
    audio_urls: list[str] = Form(default=[]),
):
    db.query(WeeklyScheduleItem).filter(
        WeeklyScheduleItem.teacher_id == current_user.id
    ).delete()

    saved_items: list[WeeklyScheduleItem] = []
    for idx, name in enumerate(item_names):
        if not name.strip():
            continue
        kind_raw = item_kinds[idx] if idx < len(item_kinds) else "subject"
        special_raw = special_types[idx] if idx < len(special_types) else ""
        weekdays = weekdays_list[idx] if idx < len(weekdays_list) else ""
        desc = item_descriptions[idx] if idx < len(item_descriptions) else ""
        link = external_links[idx] if idx < len(external_links) else ""
        audio = audio_urls[idx] if idx < len(audio_urls) else ""
        amount_raw = lesson_amounts[idx] if idx < len(lesson_amounts) else "0"
        try:
            lesson_amount = max(int(amount_raw or 0), 0)
        except ValueError:
            lesson_amount = 0

        try:
            item_kind = ScheduleItemKind(kind_raw)
        except ValueError:
            item_kind = ScheduleItemKind.subject

        special_type = None
        if special_raw:
            try:
                special_type = SpecialActivityKind(special_raw)
            except ValueError:
                special_type = None

        item = WeeklyScheduleItem(
            teacher_id=current_user.id,
            name=name.strip(),
            item_kind=item_kind,
            special_type=special_type,
            weekdays=weekdays.strip(),
            description=desc.strip() or None,
            external_link=link.strip() or None,
            audio_url=audio.strip() or None,
            lesson_amount=lesson_amount,
            sort_order=idx + 1,
        )
        db.add(item)
        saved_items.append(item)

    db.flush()

    school_year = _fetch_school_day_year(db, current_user.id)
    populated = 0
    if school_year:
        ensure_planned_days(db, school_year)
        db.flush()
        school_year = _fetch_school_day_year(db, current_user.id)
        students = _fetch_active_students(db)
        populated = populate_lesson_plans_from_subjects(
            db,
            current_user.id,
            school_year,
            saved_items,
            students,
        )

    db.commit()
    return _lesson_planning_redirect(
        cal_month=cal_month or None,
        success="yearly-subjects",
        count=str(populated) if populated else None,
    )


@router.get("/teacher/student-responses", response_class=HTMLResponse)
async def teacher_student_responses_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.teacher))],
):
    return render(
        request,
        "teacher/student_responses.html",
        {
            "user": current_user,
            "active_page": "student-responses",
            "student_responses": _fetch_student_responses(db, current_user.id),
        },
    )


@router.get("/teacher/school-days", response_class=HTMLResponse)
async def teacher_school_days_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.teacher))],
    cal_month: str | None = Query(None),
):
    school_year = _fetch_school_day_year(db, current_user.id)
    if school_year:
        ensure_planned_days(db, school_year)
        db.commit()
        school_year = _fetch_school_day_year(db, current_user.id)
    school_days = build_school_day_context(school_year, cal_month)

    return render(
        request,
        "teacher/school_days.html",
        {
            "user": current_user,
            "active_page": "school-days",
            **school_days,
        },
    )


@router.get("/teacher/school-days/attendance-report.pdf")
async def teacher_attendance_report_pdf(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.teacher))],
    disposition: str = Query("inline", pattern="^(inline|attachment)$"),
):
    school_year = _fetch_school_day_year(db, current_user.id)
    if school_year is None:
        raise HTTPException(status_code=404, detail="School year not configured")
    ensure_planned_days(db, school_year)
    db.commit()
    school_year = _fetch_school_day_year(db, current_user.id)
    attendance = collect_school_day_attendance(school_year)
    pdf_bytes = build_attendance_report_pdf(
        attendance,
        subtitle=f"Teacher: {current_user.full_name}",
    )
    filename = attendance_report_pdf_filename(
        attendance["start_date"],
        attendance["end_date"],
    )
    return RawResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers=pdf_response_headers(filename, inline=disposition == "inline"),
    )


@router.get("/teacher/lesson-plans.pdf")
async def teacher_lesson_plans_pdf(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.teacher))],
    view: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    ref_date: str | None = Query(None),
    disposition: str = Query("attachment", pattern="^(inline|attachment)$"),
):
    all_plans = _fetch_teacher_plans(db, current_user.id)
    calendar = build_calendar_context(all_plans, view, ref_date)
    pdf_bytes = build_lesson_plan_pdf(
        calendar["lesson_plans"],
        view,
        calendar["ref"],
        subtitle=f"Teacher: {current_user.full_name}",
    )
    filename = pdf_filename(view, calendar["ref"], "teacher")
    return RawResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers=pdf_response_headers(filename, inline=disposition == "inline"),
    )


@router.get("/teacher/schedule-suggestions")
async def teacher_schedule_suggestions(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.teacher))],
    plan_date: str = Query(...),
):
    try:
        parsed_date = date.fromisoformat(plan_date)
    except ValueError:
        return JSONResponse({"error": "invalid_date"}, status_code=400)

    items = (
        db.query(WeeklyScheduleItem)
        .filter(WeeklyScheduleItem.teacher_id == current_user.id)
        .order_by(WeeklyScheduleItem.sort_order, WeeklyScheduleItem.id)
        .all()
    )
    matched = schedule_items_for_date(items, parsed_date)
    return JSONResponse(
        {
            "activities": [schedule_item_to_activity(item) for item in matched],
            "weekday": parsed_date.strftime("%A"),
        }
    )


@router.post("/teacher/weekly-schedule")
async def save_weekly_schedule(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.teacher))],
    item_names: list[str] = Form(default=[]),
    item_kinds: list[str] = Form(default=[]),
    special_types: list[str] = Form(default=[]),
    weekdays_list: list[str] = Form(default=[]),
    item_descriptions: list[str] = Form(default=[]),
    external_links: list[str] = Form(default=[]),
    audio_urls: list[str] = Form(default=[]),
):
    db.query(WeeklyScheduleItem).filter(
        WeeklyScheduleItem.teacher_id == current_user.id
    ).delete()

    for idx, name in enumerate(item_names):
        if not name.strip():
            continue
        kind_raw = item_kinds[idx] if idx < len(item_kinds) else "subject"
        special_raw = special_types[idx] if idx < len(special_types) else ""
        weekdays = weekdays_list[idx] if idx < len(weekdays_list) else ""
        desc = item_descriptions[idx] if idx < len(item_descriptions) else ""
        link = external_links[idx] if idx < len(external_links) else ""
        audio = audio_urls[idx] if idx < len(audio_urls) else ""

        try:
            item_kind = ScheduleItemKind(kind_raw)
        except ValueError:
            item_kind = ScheduleItemKind.subject

        special_type = None
        if special_raw:
            try:
                special_type = SpecialActivityKind(special_raw)
            except ValueError:
                special_type = None

        db.add(
            WeeklyScheduleItem(
                teacher_id=current_user.id,
                name=name.strip(),
                item_kind=item_kind,
                special_type=special_type,
                weekdays=weekdays.strip(),
                description=desc.strip() or None,
                external_link=link.strip() or None,
                audio_url=audio.strip() or None,
                sort_order=idx + 1,
            )
        )

    db.commit()
    return RedirectResponse(
        url="/teacher/lesson-planning?success=yearly-subjects#yearly-subjects",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/teacher/lesson-plans")
async def create_lesson_plan(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.teacher))],
    title: str = Form(...),
    description: str = Form(""),
    plan_date: str = Form(...),
    student_ids: list[int] = Form(...),
    activity_titles: list[str] = Form(...),
    activity_descriptions: list[str] = Form(default=[]),
    activity_types: list[str] = Form(default=[]),
    activity_audio_urls: list[str] = Form(default=[]),
    activity_external_links: list[str] = Form(default=[]),
):
    if not student_ids:
        return _lesson_planning_redirect(plan_date=plan_date, error="students")

    try:
        parsed_date = date.fromisoformat(plan_date)
    except ValueError:
        return _lesson_planning_redirect(error="date")

    activities_data = _parse_lesson_activities(
        activity_titles,
        activity_descriptions,
        activity_types,
        activity_audio_urls,
        activity_external_links,
    )
    count = _save_lesson_plans_for_date(
        db,
        current_user.id,
        parsed_date,
        title,
        description,
        student_ids,
        activities_data,
    )
    db.commit()
    return _lesson_planning_redirect(
        cal_month=parsed_date.strftime("%Y-%m"),
        plan_date=plan_date,
        success="plan",
        count=str(count),
    )


@router.get("/teacher/school-days/possible-count")
async def school_days_possible_count(
    current_user: Annotated[User, Depends(require_roles(UserRole.teacher))],
    start_date: str = Query(...),
    end_date: str = Query(...),
):
    try:
        parsed_start = date.fromisoformat(start_date)
        parsed_end = date.fromisoformat(end_date)
    except ValueError:
        return JSONResponse({"error": "dates"}, status_code=400)

    if parsed_start > parsed_end:
        return JSONResponse({"error": "range"}, status_code=400)

    return JSONResponse(
        {"possible_days": count_possible_school_days(parsed_start, parsed_end)}
    )


@router.post("/teacher/school-days/config")
async def save_school_day_config(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.teacher))],
    start_date: str = Form(...),
    end_date: str = Form(...),
    required_days: int = Form(180),
    cal_month: str | None = Form(None),
):
    try:
        parsed_start = date.fromisoformat(start_date)
        parsed_end = date.fromisoformat(end_date)
    except ValueError:
        return _school_days_redirect(cal_month=cal_month, error="dates")

    if parsed_start > parsed_end:
        return _school_days_redirect(cal_month=cal_month, error="range")

    if required_days < 1:
        return _school_days_redirect(cal_month=cal_month, error="required")

    school_year = _fetch_school_day_year(db, current_user.id)
    if school_year:
        school_year.start_date = parsed_start
        school_year.end_date = parsed_end
        school_year.required_days = required_days
        school_year.updated_at = datetime.utcnow()
    else:
        school_year = SchoolDayYear(
            teacher_id=current_user.id,
            start_date=parsed_start,
            end_date=parsed_end,
            required_days=required_days,
        )
        db.add(school_year)
        db.flush()

    ensure_planned_days(db, school_year)
    db.commit()

    start_month = parsed_start.strftime("%Y-%m")
    return _school_days_redirect(cal_month=start_month, success="config")


@router.post("/teacher/school-days/update-day")
async def update_school_day(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.teacher))],
    day_date: str = Form(...),
    day_type: str = Form(...),
    is_completed: str = Form("false"),
    cal_month: str | None = Form(None),
):
    ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    school_year = _fetch_school_day_year(db, current_user.id)
    if not school_year:
        if ajax:
            return JSONResponse({"error": "config"}, status_code=400)
        return _school_days_redirect(cal_month=cal_month, error="config")

    try:
        parsed_day = date.fromisoformat(day_date)
    except ValueError:
        if ajax:
            return JSONResponse({"error": "date"}, status_code=400)
        return _school_days_redirect(cal_month=cal_month, error="date")

    if not (school_year.start_date <= parsed_day <= school_year.end_date):
        if ajax:
            return JSONResponse({"error": "range"}, status_code=400)
        return _school_days_redirect(cal_month=cal_month, error="range")

    try:
        parsed_type = SchoolDayType(day_type)
    except ValueError:
        if ajax:
            return JSONResponse({"error": "type"}, status_code=400)
        return _school_days_redirect(cal_month=cal_month, error="date")

    completed = is_completed.lower() in ("true", "1", "on")
    if parsed_type != SchoolDayType.actual_school:
        completed = False

    planned = (
        db.query(PlannedSchoolDay)
        .filter(
            PlannedSchoolDay.school_day_year_id == school_year.id,
            PlannedSchoolDay.day_date == parsed_day,
        )
        .first()
    )
    if not planned:
        ensure_planned_days(db, school_year)
        db.flush()
        planned = (
            db.query(PlannedSchoolDay)
            .filter(
                PlannedSchoolDay.school_day_year_id == school_year.id,
                PlannedSchoolDay.day_date == parsed_day,
            )
            .first()
        )

    planned.day_type = parsed_type
    planned.is_completed = completed
    planned.updated_at = datetime.utcnow()
    db.commit()

    if ajax:
        school_year = _fetch_school_day_year(db, current_user.id)
        counts = planned_day_counts(school_year)
        required_days = school_year.required_days
        completed_count = counts["completed_count"]
        holiday_name = holiday_name_for_date(
            parsed_day, school_year.start_date, school_year.end_date
        )
        return JSONResponse(
            {
                "day_type": parsed_type.value,
                "is_completed": completed,
                "holiday_name": holiday_name,
                "planned_actual_count": counts["planned_actual_count"],
                "planned_school_off_count": counts["planned_school_off_count"],
                "completed_count": completed_count,
                "required_days": required_days,
                "remaining_days": max(required_days - completed_count, 0),
                "complete": completed_count >= required_days,
            }
        )

    return _school_days_redirect(cal_month=cal_month)


def _fetch_student_plans(db: Session, student_id: int) -> list[LessonPlan]:
    plans = (
        db.query(LessonPlan)
        .options(joinedload(LessonPlan.activities), joinedload(LessonPlan.teacher))
        .filter(LessonPlan.student_id == student_id)
        .order_by(LessonPlan.plan_date.desc())
        .all()
    )
    return _visible_lesson_plans(db, plans)


@router.get("/student", response_class=HTMLResponse)
async def student_dashboard(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.student))],
    view: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    ref_date: str | None = Query(None),
):
    all_plans = _fetch_student_plans(db, current_user.id)
    calendar = build_calendar_context(all_plans, view, ref_date)
    ref = calendar["ref"]
    today = date.today()

    lesson_plan = None
    completions: dict[int, dict] = {}
    progress = 0
    done_count = 0
    total_count = 0
    show_interactive = view == "daily" and ref == today

    if show_interactive and calendar["lesson_plans"]:
        lesson_plan = calendar["lesson_plans"][0]
        plan_completions = load_completions_for_plans(db, current_user.id, [lesson_plan])
        completions = plan_completions.get(lesson_plan.id, {})
        total_count = len(lesson_plan.activities)
        done_count = sum(1 for v in completions.values() if v.get("completed"))
        progress = int((done_count / total_count) * 100) if total_count else 0

    all_completions = load_completions_for_plans(db, current_user.id, calendar["lesson_plans"])

    return render(
        request,
        "student/dashboard.html",
        {
            "user": current_user,
            "today": today,
            "base_path": "/student",
            "pdf_path": "/student/lesson-plans.pdf",
            "plan_card_partial": "student/partials/plan_card.html",
            "empty_hint": "Check back later — your teacher may add activities soon!",
            "lesson_plan": lesson_plan,
            "completions": completions,
            "progress": progress,
            "done_count": done_count,
            "total_count": total_count,
            "show_interactive": show_interactive,
            "all_completions": all_completions,
            **calendar,
        },
    )


@router.get("/student/lesson-plans.pdf")
async def student_lesson_plans_pdf(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.student))],
    view: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    ref_date: str | None = Query(None),
    disposition: str = Query("attachment", pattern="^(inline|attachment)$"),
):
    all_plans = _fetch_student_plans(db, current_user.id)
    calendar = build_calendar_context(all_plans, view, ref_date)
    completions_by_plan = load_completions_for_plans(db, current_user.id, calendar["lesson_plans"])
    pdf_bytes = build_lesson_plan_pdf(
        calendar["lesson_plans"],
        view,
        calendar["ref"],
        subtitle=f"Student: {current_user.full_name}",
        completions_by_plan=completions_by_plan,
    )
    filename = pdf_filename(view, calendar["ref"], "student")
    return RawResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers=pdf_response_headers(filename, inline=disposition == "inline"),
    )


@router.post("/student/activities/{activity_id}/toggle")
async def toggle_activity(
    activity_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.student))],
):
    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    plan = db.query(LessonPlan).filter(LessonPlan.id == activity.lesson_plan_id).first()
    if not plan or plan.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your activity")

    completion = (
        db.query(ActivityCompletion)
        .filter(
            ActivityCompletion.activity_id == activity_id,
            ActivityCompletion.student_id == current_user.id,
        )
        .first()
    )
    if completion:
        completion.completed = not completion.completed
        completion.completed_at = datetime.utcnow() if completion.completed else None
    else:
        completion = ActivityCompletion(
            activity_id=activity_id,
            student_id=current_user.id,
            completed=True,
            completed_at=datetime.utcnow(),
        )
        db.add(completion)
    db.commit()
    return RedirectResponse(url="/student", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/student/activities/{activity_id}/message")
async def submit_activity_message(
    activity_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.student))],
    student_message: str = Form(""),
):
    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    plan = db.query(LessonPlan).filter(LessonPlan.id == activity.lesson_plan_id).first()
    if not plan or plan.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your activity")

    message = student_message.strip()
    if not message:
        return RedirectResponse(url="/student", status_code=status.HTTP_303_SEE_OTHER)

    completion = (
        db.query(ActivityCompletion)
        .filter(
            ActivityCompletion.activity_id == activity_id,
            ActivityCompletion.student_id == current_user.id,
        )
        .first()
    )
    if completion:
        completion.student_message = message
        completion.completed_at = datetime.utcnow()
    else:
        completion = ActivityCompletion(
            activity_id=activity_id,
            student_id=current_user.id,
            completed=False,
            student_message=message,
            completed_at=datetime.utcnow(),
        )
        db.add(completion)
    db.commit()
    return RedirectResponse(url="/student?success=message", status_code=status.HTTP_303_SEE_OTHER)
