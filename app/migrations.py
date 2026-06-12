from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.models import AppSetting


def _column_exists(inspector, table: str, column: str) -> bool:
    return column in {col["name"] for col in inspector.get_columns(table)}


def _table_exists(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


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
