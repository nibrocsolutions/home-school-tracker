from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models import Activity, LessonPlan, User, UserRole

WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

DEMO_PROFILES = {
    "admin": ("Robert", "Corbin"),
    "administrator": ("Joe", "Principal"),
    "teacher": ("Jenny", "Corbin"),
    "student": ("Ella", "Corbin"),
}


def day_name(plan_date: date) -> str:
    return plan_date.strftime("%A")


def fix_lesson_plan_weekday_titles(db: Session) -> None:
    for plan in db.query(LessonPlan).all():
        correct = plan.plan_date.strftime("%A")
        for weekday in WEEKDAYS:
            if weekday in plan.title and weekday != correct:
                plan.title = plan.title.replace(weekday, correct)
                break
    db.commit()


def update_demo_profiles(db: Session) -> None:
    changed = False
    for username, (first_name, last_name) in DEMO_PROFILES.items():
        user = db.query(User).filter(User.username == username).first()
        if user and (user.first_name != first_name or user.last_name != last_name):
            user.first_name = first_name
            user.last_name = last_name
            changed = True
    if changed:
        db.commit()
    fix_lesson_plan_weekday_titles(db)


def seed_database(db: Session) -> None:
    if db.query(User).first():
        update_demo_profiles(db)
        return

    users = [
        User(
            username="admin",
            email="admin@homeschool.local",
            password_hash=hash_password("admin123"),
            role=UserRole.admin,
            first_name="Robert",
            last_name="Corbin",
        ),
        User(
            username="administrator",
            email="administrator@homeschool.local",
            password_hash=hash_password("admin123"),
            role=UserRole.administrator,
            first_name="Joe",
            last_name="Principal",
        ),
        User(
            username="teacher",
            email="teacher@homeschool.local",
            password_hash=hash_password("teacher123"),
            role=UserRole.teacher,
            first_name="Jenny",
            last_name="Corbin",
        ),
        User(
            username="student",
            email="student@homeschool.local",
            password_hash=hash_password("student123"),
            role=UserRole.student,
            first_name="Ella",
            last_name="Corbin",
        ),
        User(
            username="student2",
            email="student2@homeschool.local",
            password_hash=hash_password("student123"),
            role=UserRole.student,
            first_name="Morgan",
            last_name="Patel",
        ),
    ]
    db.add_all(users)
    db.flush()

    teacher = next(u for u in users if u.role == UserRole.teacher)
    ella = next(u for u in users if u.username == "student")
    morgan = next(u for u in users if u.username == "student2")
    today = date.today()
    tomorrow = today + timedelta(days=1)
    yesterday = today - timedelta(days=1)

    plans = [
        LessonPlan(
            title=f"Math & Science {day_name(today)}",
            description="Kick off the day with numbers, experiments, and curiosity!",
            plan_date=today,
            teacher_id=teacher.id,
            student_id=ella.id,
            activities=[
                Activity(
                    title="Morning Math Warm-up",
                    description="Complete 15 multiplication problems in your workbook (pages 42–43).",
                    sort_order=1,
                ),
                Activity(
                    title="Science Experiment: Volcano Eruption",
                    description="Build a baking soda volcano and record your observations in your lab notebook.",
                    sort_order=2,
                ),
                Activity(
                    title="Reading Break",
                    description="Read Chapter 4 of 'The Wild Robot' for 20 minutes.",
                    sort_order=3,
                ),
                Activity(
                    title="Journal Reflection",
                    description="Write 3 sentences about what you learned today.",
                    sort_order=4,
                    is_required=False,
                ),
            ],
        ),
        LessonPlan(
            title=f"Language Arts & History — {day_name(today)}",
            description="Stories from the past and words that paint pictures.",
            plan_date=today,
            teacher_id=teacher.id,
            student_id=morgan.id,
            activities=[
                Activity(
                    title="Grammar Practice",
                    description="Complete the adjective and adverb worksheet.",
                    sort_order=1,
                ),
                Activity(
                    title="History Timeline",
                    description="Add 5 events to your American Revolution timeline.",
                    sort_order=2,
                ),
                Activity(
                    title="Creative Writing",
                    description="Write a short story from the perspective of a historical figure.",
                    sort_order=3,
                ),
            ],
        ),
        LessonPlan(
            title=f"Outdoor Exploration {day_name(tomorrow)}",
            description="Nature walk and geography adventures.",
            plan_date=tomorrow,
            teacher_id=teacher.id,
            student_id=ella.id,
            activities=[
                Activity(
                    title="Nature Walk",
                    description="Identify 10 plants or insects in your backyard or local park.",
                    sort_order=1,
                ),
                Activity(
                    title="Map Skills",
                    description="Label continents and oceans on a blank world map.",
                    sort_order=2,
                ),
            ],
        ),
        LessonPlan(
            title=f"Review & Reflection {day_name(yesterday)}",
            description="Look back at the week and strengthen key skills.",
            plan_date=yesterday,
            teacher_id=teacher.id,
            student_id=ella.id,
            activities=[
                Activity(
                    title="Spelling Review",
                    description="Practice this week's vocabulary words.",
                    sort_order=1,
                ),
                Activity(
                    title="Math Quiz",
                    description="Complete the 10-question review worksheet.",
                    sort_order=2,
                ),
            ],
        ),
    ]
    db.add_all(plans)
    db.commit()
