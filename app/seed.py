from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.migrations import run_schema_migrations
from app.models import (
    Activity,
    ActivityCompletion,
    ActivityType,
    AppSetting,
    LessonPlan,
    ScheduleItemKind,
    SpecialActivityKind,
    User,
    UserRole,
    WeeklyScheduleItem,
)
from app.sample_plans import HISTORY_AUDIO_URL

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
    "teacher": ("Jenny", "Corbin"),
    "student": ("Ella", "Corbin"),
}

STUDENT_PROFILES = {
    "student": (10, "4th Grade"),
}


def migrate_legacy_roles(db: Session) -> None:
    db.execute(text("UPDATE users SET role = 'admin' WHERE role::text = 'administrator'"))
    db.commit()


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


def remove_extra_demo_students(db: Session) -> None:
    """Keep only Ella Corbin (username=student) as the default demo student."""
    extra = (
        db.query(User)
        .filter(User.username == "student2", User.role == UserRole.student)
        .first()
    )
    if extra is None:
        return

    plan_ids = [
        row[0]
        for row in db.query(LessonPlan.id).filter(LessonPlan.student_id == extra.id).all()
    ]
    if plan_ids:
        activity_ids = [
            row[0]
            for row in db.query(Activity.id).filter(Activity.lesson_plan_id.in_(plan_ids)).all()
        ]
        if activity_ids:
            db.query(ActivityCompletion).filter(
                ActivityCompletion.activity_id.in_(activity_ids)
            ).delete(synchronize_session=False)
            db.query(Activity).filter(Activity.id.in_(activity_ids)).delete(
                synchronize_session=False
            )
        db.query(LessonPlan).filter(LessonPlan.id.in_(plan_ids)).delete(
            synchronize_session=False
        )

    # Drop schedule assignments for the extra demo student.
    db.execute(
        text("DELETE FROM weekly_schedule_item_students WHERE student_id = :student_id"),
        {"student_id": extra.id},
    )
    db.delete(extra)
    db.commit()


def update_demo_profiles(db: Session) -> None:
    changed = False
    for username, (first_name, last_name) in DEMO_PROFILES.items():
        user = db.query(User).filter(User.username == username).first()
        if user and (user.first_name != first_name or user.last_name != last_name):
            user.first_name = first_name
            user.last_name = last_name
            changed = True
    for username, (age, grade) in STUDENT_PROFILES.items():
        user = db.query(User).filter(User.username == username).first()
        if user and user.role == UserRole.student:
            if user.age != age or user.grade != grade:
                user.age = age
                user.grade = grade
                changed = True
    if changed:
        db.commit()
    fix_lesson_plan_weekday_titles(db)
    remove_extra_demo_students(db)


def seed_default_weekly_schedule(db: Session, teacher_id: int) -> None:
    if db.query(WeeklyScheduleItem).filter(WeeklyScheduleItem.teacher_id == teacher_id).first():
        return

    defaults = [
        WeeklyScheduleItem(
            teacher_id=teacher_id,
            name="Co-Op",
            item_kind=ScheduleItemKind.special_activity,
            special_type=SpecialActivityKind.co_op,
            weekdays="",
            description="Community co-op classes with other homeschool families.",
            lesson_amount=36,
            sort_order=1,
        ),
        WeeklyScheduleItem(
            teacher_id=teacher_id,
            name="Wild and Free Outing",
            item_kind=ScheduleItemKind.special_activity,
            special_type=SpecialActivityKind.wild_and_free,
            weekdays="",
            description="Outdoor nature exploration and adventure learning.",
            lesson_amount=36,
            sort_order=2,
        ),
        WeeklyScheduleItem(
            teacher_id=teacher_id,
            name="Classical Conversations Essentials",
            item_kind=ScheduleItemKind.special_activity,
            special_type=SpecialActivityKind.classical_conversations,
            weekdays="",
            description="Essentials program — grammar, writing, and presentations.",
            external_link="https://classicalconversations.com/programs/essentials/",
            lesson_amount=36,
            sort_order=3,
        ),
        WeeklyScheduleItem(
            teacher_id=teacher_id,
            name="History",
            item_kind=ScheduleItemKind.subject,
            weekdays="",
            description="Listen to the history audio lesson and share what you learned.",
            external_link=HISTORY_AUDIO_URL,
            lesson_amount=72,
            include_numbering=True,
            sort_order=4,
        ),
        WeeklyScheduleItem(
            teacher_id=teacher_id,
            name="Math",
            item_kind=ScheduleItemKind.subject,
            weekdays="",
            description="Complete math workbook pages and practice problems.",
            lesson_amount=120,
            include_numbering=True,
            sort_order=5,
        ),
        WeeklyScheduleItem(
            teacher_id=teacher_id,
            name="Language Arts",
            item_kind=ScheduleItemKind.subject,
            weekdays="",
            description="Grammar, spelling, and creative writing.",
            lesson_amount=120,
            include_numbering=True,
            sort_order=6,
        ),
        WeeklyScheduleItem(
            teacher_id=teacher_id,
            name="Science",
            item_kind=ScheduleItemKind.subject,
            weekdays="",
            description="Hands-on experiments, observations, and science workbook lessons.",
            lesson_amount=120,
            include_numbering=True,
            sort_order=7,
        ),
    ]
    db.add_all(defaults)
    db.commit()


def seed_database(db: Session) -> None:
    migrate_legacy_roles(db)
    run_schema_migrations(db)

    settings = db.query(AppSetting).first()
    if not settings:
        db.add(AppSetting(sample_lesson_plans_enabled=False, sample_data_enabled=False))
        db.commit()

    if db.query(User).first():
        update_demo_profiles(db)
        teacher = db.query(User).filter(User.role == UserRole.teacher).first()
        if teacher:
            seed_default_weekly_schedule(db, teacher.id)
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
            age=10,
            grade="4th Grade",
        ),
    ]
    db.add_all(users)
    db.flush()

    teacher = next(u for u in users if u.role == UserRole.teacher)
    ella = next(u for u in users if u.username == "student")
    today = date.today()
    tomorrow = today + timedelta(days=1)
    yesterday = today - timedelta(days=1)

    seed_default_weekly_schedule(db, teacher.id)

    plans = [
        LessonPlan(
            title=f"Math & Science {day_name(today)}",
            description="Kick off the day with numbers, experiments, and curiosity!",
            plan_date=today,
            teacher_id=teacher.id,
            student_id=ella.id,
            is_sample_data=True,
            activities=[
                Activity(
                    title="Morning Math Warm-up",
                    description="Complete 15 multiplication problems in your workbook (pages 42–43).",
                    sort_order=1,
                    activity_type=ActivityType.regular,
                ),
                Activity(
                    title="Science Experiment: Volcano Eruption",
                    description="Build a baking soda volcano and record your observations in your lab notebook.",
                    sort_order=2,
                    activity_type=ActivityType.regular,
                ),
                Activity(
                    title="Reading Break",
                    description="Read Chapter 4 of 'The Wild Robot' for 20 minutes.",
                    sort_order=3,
                    activity_type=ActivityType.subject,
                ),
                Activity(
                    title="Journal Reflection",
                    description="Write 3 sentences about what you learned today.",
                    sort_order=4,
                    is_required=False,
                    activity_type=ActivityType.regular,
                ),
            ],
        ),
        LessonPlan(
            title=f"Language Arts & History — {day_name(today)}",
            description="Stories from the past and words that paint pictures.",
            plan_date=today,
            teacher_id=teacher.id,
            student_id=ella.id,
            is_sample_data=True,
            activities=[
                Activity(
                    title="Grammar Practice",
                    description="Complete the adjective and adverb worksheet.",
                    sort_order=1,
                    activity_type=ActivityType.subject,
                ),
                Activity(
                    title="History Audio Lesson",
                    description="Listen to the history lesson audio, then tell your teacher what you learned.",
                    sort_order=2,
                    activity_type=ActivityType.history,
                    teacher_notes="History audio is available from the subject resource link.",
                    external_link=HISTORY_AUDIO_URL,
                ),
                Activity(
                    title="Creative Writing",
                    description="Write a short story from the perspective of a historical figure.",
                    sort_order=3,
                    activity_type=ActivityType.regular,
                ),
            ],
        ),
        LessonPlan(
            title=f"Outdoor Exploration {day_name(tomorrow)}",
            description="Nature walk and geography adventures.",
            plan_date=tomorrow,
            teacher_id=teacher.id,
            student_id=ella.id,
            is_sample_data=True,
            activities=[
                Activity(
                    title="Wild and Free Outing",
                    description="Identify 10 plants or insects in your backyard or local park.",
                    sort_order=1,
                    activity_type=ActivityType.special,
                ),
                Activity(
                    title="Map Skills",
                    description="Label continents and oceans on a blank world map.",
                    sort_order=2,
                    activity_type=ActivityType.subject,
                ),
            ],
        ),
        LessonPlan(
            title=f"Review & Reflection {day_name(yesterday)}",
            description="Look back at the week and strengthen key skills.",
            plan_date=yesterday,
            teacher_id=teacher.id,
            student_id=ella.id,
            is_sample_data=True,
            activities=[
                Activity(
                    title="Spelling Review",
                    description="Practice this week's vocabulary words.",
                    sort_order=1,
                    activity_type=ActivityType.subject,
                ),
                Activity(
                    title="Math Quiz",
                    description="Complete the 10-question review worksheet.",
                    sort_order=2,
                    activity_type=ActivityType.regular,
                ),
            ],
        ),
    ]
    db.add_all(plans)
    db.commit()
