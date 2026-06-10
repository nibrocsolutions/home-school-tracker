from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
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
from app.calendar_utils import (
    build_month_grid,
    filter_plans_by_view,
    group_plans_by_date,
    month_end,
    month_start,
    parse_ref_date,
    period_label,
    shift_ref_date,
    week_end,
    week_start,
)
from app.database import get_db
from app.models import Activity, ActivityCompletion, LessonPlan, User, UserRole

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def render(request: Request, name: str, context: dict, status_code: int = 200):
    base = {"request": request, "app_name": "Home School Tracker"}
    base.update(context)
    return templates.TemplateResponse(name, base, status_code=status_code)


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


@router.get("/administrator", response_class=HTMLResponse)
async def administrator_dashboard(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.administrator, UserRole.admin))],
):
    admins = db.query(User).filter(User.role == UserRole.admin).all()
    administrators = db.query(User).filter(User.role == UserRole.administrator).all()
    teachers = db.query(User).filter(User.role == UserRole.teacher).all()
    students = db.query(User).filter(User.role == UserRole.student).all()
    return render(
        request,
        "administrator/dashboard.html",
        {
            "user": current_user,
            "admins": admins,
            "administrators": administrators,
            "teachers": teachers,
            "students": students,
        },
    )


@router.post("/administrator/users")
async def create_user(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.administrator, UserRole.admin))],
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    role: str = Form(...),
):
    if db.query(User).filter((User.username == username) | (User.email == email)).first():
        return RedirectResponse(
            url="/administrator?error=exists",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    try:
        user_role = UserRole(role)
    except ValueError:
        return RedirectResponse(
            url="/administrator?error=role",
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
    return RedirectResponse(url="/administrator?success=created", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/administrator/users/{user_id}/toggle")
async def toggle_user(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.administrator, UserRole.admin))],
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        return RedirectResponse(
            url="/administrator?error=self",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    user.is_active = not user.is_active
    db.commit()
    return RedirectResponse(url="/administrator", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/teacher", response_class=HTMLResponse)
async def teacher_dashboard(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.teacher))],
    view: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    ref_date: str | None = Query(None),
):
    students = db.query(User).filter(User.role == UserRole.student, User.is_active == True).all()
    all_plans = (
        db.query(LessonPlan)
        .options(joinedload(LessonPlan.activities), joinedload(LessonPlan.student))
        .filter(LessonPlan.teacher_id == current_user.id)
        .order_by(LessonPlan.plan_date.desc())
        .all()
    )

    ref = parse_ref_date(ref_date)
    lesson_plans = filter_plans_by_view(all_plans, view, ref)
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
        month_plan_dates = {p.plan_date for p in all_plans if month_start(ref) <= p.plan_date <= month_end(ref)}
        month_grid = build_month_grid(ref, month_plan_dates)

    prev_ref = shift_ref_date(ref, view, -1).isoformat()
    next_ref = shift_ref_date(ref, view, 1).isoformat()

    return render(
        request,
        "teacher/dashboard.html",
        {
            "user": current_user,
            "students": students,
            "lesson_plans": lesson_plans,
            "grouped_plans": grouped_plans,
            "sorted_grouped_plans": sorted_grouped_plans,
            "today": date.today().isoformat(),
            "view": view,
            "ref_date": ref.isoformat(),
            "period_label": period_label(view, ref),
            "prev_ref": prev_ref,
            "next_ref": next_ref,
            "week_days": week_days,
            "month_grid": month_grid,
        },
    )


@router.post("/teacher/lesson-plans")
async def create_lesson_plan(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.teacher))],
    title: str = Form(...),
    description: str = Form(""),
    plan_date: str = Form(...),
    student_id: int = Form(...),
    activity_titles: list[str] = Form(...),
    activity_descriptions: list[str] = Form(default=[]),
):
    plan = LessonPlan(
        title=title,
        description=description or None,
        plan_date=date.fromisoformat(plan_date),
        teacher_id=current_user.id,
        student_id=student_id,
    )
    db.add(plan)
    db.flush()

    for idx, act_title in enumerate(activity_titles):
        if not act_title.strip():
            continue
        desc = activity_descriptions[idx] if idx < len(activity_descriptions) else ""
        db.add(
            Activity(
                lesson_plan_id=plan.id,
                title=act_title.strip(),
                description=desc.strip() or None,
                sort_order=idx + 1,
            )
        )
    db.commit()
    return RedirectResponse(url="/teacher?success=plan", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/student", response_class=HTMLResponse)
async def student_dashboard(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.student))],
):
    today = date.today()
    lesson_plan = (
        db.query(LessonPlan)
        .options(joinedload(LessonPlan.activities), joinedload(LessonPlan.teacher))
        .filter(LessonPlan.student_id == current_user.id, LessonPlan.plan_date == today)
        .first()
    )

    completions = {}
    if lesson_plan:
        for activity in lesson_plan.activities:
            completion = (
                db.query(ActivityCompletion)
                .filter(
                    ActivityCompletion.activity_id == activity.id,
                    ActivityCompletion.student_id == current_user.id,
                )
                .first()
            )
            completions[activity.id] = completion.completed if completion else False

    total = len(lesson_plan.activities) if lesson_plan else 0
    done = sum(1 for v in completions.values() if v)
    progress = int((done / total) * 100) if total else 0

    return render(
        request,
        "student/dashboard.html",
        {
            "user": current_user,
            "lesson_plan": lesson_plan,
            "completions": completions,
            "progress": progress,
            "done_count": done,
            "total_count": total,
            "today": today,
        },
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
