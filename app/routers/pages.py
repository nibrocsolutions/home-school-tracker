from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response as RawResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.auth import (
    ROLE_HOME_PAGES,
    authenticate_user,
    create_access_token,
    get_current_user,
    hash_password,
    require_roles,
)
from app.backup import export_database, import_database
from app.calendar_context import build_calendar_context
from app.database import get_db
from app.models import Activity, ActivityCompletion, LessonPlan, User, UserRole
from app.pdf_export import build_lesson_plan_pdf, pdf_filename, pdf_response_headers

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def render(request: Request, name: str, context: dict, status_code: int = 200):
    base = {"request": request, "app_name": "Home School Tracker"}
    base.update(context)
    return templates.TemplateResponse(name, base, status_code=status_code)


def load_completions_for_plans(
    db: Session, student_id: int, plans: list[LessonPlan]
) -> dict[int, dict[int, bool]]:
    result: dict[int, dict[int, bool]] = {}
    for plan in plans:
        activity_map: dict[int, bool] = {}
        for activity in plan.activities:
            completion = (
                db.query(ActivityCompletion)
                .filter(
                    ActivityCompletion.activity_id == activity.id,
                    ActivityCompletion.student_id == student_id,
                )
                .first()
            )
            activity_map[activity.id] = completion.completed if completion else False
        result[plan.id] = activity_map
    return result


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return render(request, "login.html", {})


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

    new_user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        role=user_role,
        first_name=first_name,
        last_name=last_name,
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse(url="/admin/users?success=created", status_code=status.HTTP_303_SEE_OTHER)


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


def _fetch_teacher_plans(db: Session, teacher_id: int) -> list[LessonPlan]:
    return (
        db.query(LessonPlan)
        .options(joinedload(LessonPlan.activities), joinedload(LessonPlan.student))
        .filter(LessonPlan.teacher_id == teacher_id)
        .order_by(LessonPlan.plan_date.desc())
        .all()
    )


@router.get("/teacher", response_class=HTMLResponse)
async def teacher_dashboard(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.teacher))],
    view: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    ref_date: str | None = Query(None),
):
    students = db.query(User).filter(User.role == UserRole.student, User.is_active == True).all()
    all_plans = _fetch_teacher_plans(db, current_user.id)
    calendar = build_calendar_context(all_plans, view, ref_date)

    return render(
        request,
        "teacher/dashboard.html",
        {
            "user": current_user,
            "students": students,
            "today": date.today().isoformat(),
            "base_path": "/teacher",
            "pdf_path": "/teacher/lesson-plans.pdf",
            "plan_card_partial": "teacher/partials/plan_card.html",
            "empty_hint": "Create one to get started!",
            **calendar,
        },
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
):
    if not student_ids:
        return RedirectResponse(
            url="/teacher?error=students",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    activities_data = []
    for idx, act_title in enumerate(activity_titles):
        if not act_title.strip():
            continue
        desc = activity_descriptions[idx] if idx < len(activity_descriptions) else ""
        activities_data.append((act_title.strip(), desc.strip() or None, idx + 1))

    parsed_date = date.fromisoformat(plan_date)
    for student_id in student_ids:
        plan = LessonPlan(
            title=title,
            description=description or None,
            plan_date=parsed_date,
            teacher_id=current_user.id,
            student_id=student_id,
        )
        db.add(plan)
        db.flush()
        for act_title, act_desc, sort_order in activities_data:
            db.add(
                Activity(
                    lesson_plan_id=plan.id,
                    title=act_title,
                    description=act_desc,
                    sort_order=sort_order,
                )
            )
    db.commit()
    count = len(student_ids)
    return RedirectResponse(
        url=f"/teacher?success=plan&count={count}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _fetch_student_plans(db: Session, student_id: int) -> list[LessonPlan]:
    return (
        db.query(LessonPlan)
        .options(joinedload(LessonPlan.activities), joinedload(LessonPlan.teacher))
        .filter(LessonPlan.student_id == student_id)
        .order_by(LessonPlan.plan_date.desc())
        .all()
    )


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
    completions: dict[int, bool] = {}
    progress = 0
    done_count = 0
    total_count = 0
    show_interactive = view == "daily" and ref == today

    if show_interactive and calendar["lesson_plans"]:
        lesson_plan = calendar["lesson_plans"][0]
        plan_completions = load_completions_for_plans(db, current_user.id, [lesson_plan])
        completions = plan_completions.get(lesson_plan.id, {})
        total_count = len(lesson_plan.activities)
        done_count = sum(1 for v in completions.values() if v)
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
    from datetime import datetime

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
