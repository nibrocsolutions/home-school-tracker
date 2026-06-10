from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models import Activity, LessonPlan, User, UserRole


def seed_database(db: Session) -> None:
    if db.query(User).first():
        return

    users = [
        User(
            username="admin",
            email="admin@homeschool.local",
            password_hash=hash_password("admin123"),
            role=UserRole.admin,
            first_name="Alex",
            last_name="Rivera",
        ),
        User(
            username="administrator",
            email="administrator@homeschool.local",
            password_hash=hash_password("admin123"),
            role=UserRole.administrator,
            first_name="Jordan",
            last_name="Mitchell",
        ),
        User(
            username="teacher",
            email="teacher@homeschool.local",
            password_hash=hash_password("teacher123"),
            role=UserRole.teacher,
            first_name="Sam",
            last_name="Chen",
        ),
        User(
            username="student",
            email="student@homeschool.local",
            password_hash=hash_password("student123"),
            role=UserRole.student,
            first_name="Riley",
            last_name="Chen",
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
    riley = next(u for u in users if u.username == "student")
    morgan = next(u for u in users if u.username == "student2")
    today = date.today()

    plans = [
        LessonPlan(
            title="Math & Science Monday",
            description="Kick off the week with numbers, experiments, and curiosity!",
            plan_date=today,
            teacher_id=teacher.id,
            student_id=riley.id,
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
            title="Language Arts & History",
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
            title="Outdoor Exploration Tuesday",
            description="Tomorrow's preview — nature walk and geography.",
            plan_date=today + timedelta(days=1),
            teacher_id=teacher.id,
            student_id=riley.id,
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
    ]
    db.add_all(plans)
    db.commit()
