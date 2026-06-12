from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.models import AppSetting, LessonPlan, User


def _column_exists(inspector, table: str, column: str) -> bool:
    return column in {col["name"] for col in inspector.get_columns(table)}


def _table_exists(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _mark_existing_sample_lesson_plans(db: Session) -> None:
    demo_teacher = db.query(User).filter(User.username == "teacher").first()
    if not demo_teacher:
        return
    demo_student_ids = [
        user.id
        for user in db.query(User).filter(User.username.in_(["student", "student2"])).all()
    ]
    if not demo_student_ids:
        return
    db.query(LessonPlan).filter(
        LessonPlan.teacher_id == demo_teacher.id,
        LessonPlan.student_id.in_(demo_student_ids),
    ).update({LessonPlan.is_sample_data: True}, synchronize_session=False)
    db.commit()


def run_schema_migrations(db: Session) -> None:
    bind = db.get_bind()
    inspector = inspect(bind)

    if _table_exists(inspector, "users"):
        if not _column_exists(inspector, "users", "age"):
            db.execute(text("ALTER TABLE users ADD COLUMN age INTEGER"))
        if not _column_exists(inspector, "users", "grade"):
            db.execute(text("ALTER TABLE users ADD COLUMN grade VARCHAR(30)"))

    if _table_exists(inspector, "activities"):
        if not _column_exists(inspector, "activities", "activity_type"):
            db.execute(
                text(
                    "ALTER TABLE activities ADD COLUMN activity_type VARCHAR(20) "
                    "NOT NULL DEFAULT 'regular'"
                )
            )
        if not _column_exists(inspector, "activities", "audio_url"):
            db.execute(text("ALTER TABLE activities ADD COLUMN audio_url VARCHAR(500)"))
        if not _column_exists(inspector, "activities", "external_link"):
            db.execute(text("ALTER TABLE activities ADD COLUMN external_link VARCHAR(500)"))

    if _table_exists(inspector, "activity_completions"):
        if not _column_exists(inspector, "activity_completions", "student_message"):
            db.execute(text("ALTER TABLE activity_completions ADD COLUMN student_message TEXT"))

    db.commit()

    if not _table_exists(inspector, "app_settings"):
        db.add(AppSetting(sample_lesson_plans_enabled=False, sample_data_enabled=False))
        db.commit()
    elif _table_exists(inspector, "app_settings"):
        if not _column_exists(inspector, "app_settings", "sample_data_enabled"):
            db.execute(
                text(
                    "ALTER TABLE app_settings ADD COLUMN sample_data_enabled BOOLEAN "
                    "NOT NULL DEFAULT FALSE"
                )
            )
            db.commit()

    if _table_exists(inspector, "lesson_plans"):
        if not _column_exists(inspector, "lesson_plans", "is_sample_data"):
            db.execute(
                text(
                    "ALTER TABLE lesson_plans ADD COLUMN is_sample_data BOOLEAN "
                    "NOT NULL DEFAULT FALSE"
                )
            )
            db.commit()
            _mark_existing_sample_lesson_plans(db)

    _migrate_planned_school_days(db, inspector)


def _migrate_planned_school_days(db: Session, inspector) -> None:
    if not _table_exists(inspector, "planned_school_days"):
        db.execute(
            text(
                "CREATE TABLE planned_school_days ("
                "id INTEGER NOT NULL PRIMARY KEY, "
                "school_day_year_id INTEGER NOT NULL, "
                "day_date DATE NOT NULL, "
                "day_type VARCHAR(20) NOT NULL DEFAULT 'actual_school', "
                "is_completed BOOLEAN NOT NULL DEFAULT 0, "
                "updated_at DATETIME, "
                "FOREIGN KEY(school_day_year_id) REFERENCES school_day_years (id), "
                "CONSTRAINT uq_school_day_year_date UNIQUE (school_day_year_id, day_date)"
                ")"
            )
        )
        db.commit()
        inspector = inspect(db.get_bind())

    if _table_exists(inspector, "approved_school_days"):
        db.execute(
            text(
                "INSERT OR IGNORE INTO planned_school_days "
                "(school_day_year_id, day_date, day_type, is_completed, updated_at) "
                "SELECT school_day_year_id, day_date, 'actual_school', 1, approved_at "
                "FROM approved_school_days"
            )
        )
        db.execute(text("DROP TABLE approved_school_days"))
        db.commit()
