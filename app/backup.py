import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import (
    Activity,
    ActivityCompletion,
    ApprovedSchoolDay,
    LessonPlan,
    SchoolDayYear,
    User,
    UserRole,
)

BACKUP_VERSION = 1


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _serialize_date(value: date) -> str:
    return value.isoformat()


def export_database(db: Session) -> bytes:
    payload = {
        "version": BACKUP_VERSION,
        "exported_at": datetime.utcnow().isoformat(),
        "users": [
            {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "password_hash": user.password_hash,
                "role": user.role.value,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_active": user.is_active,
                "created_at": _serialize_datetime(user.created_at),
            }
            for user in db.query(User).order_by(User.id).all()
        ],
        "lesson_plans": [
            {
                "id": plan.id,
                "title": plan.title,
                "description": plan.description,
                "plan_date": _serialize_date(plan.plan_date),
                "teacher_id": plan.teacher_id,
                "student_id": plan.student_id,
                "created_at": _serialize_datetime(plan.created_at),
            }
            for plan in db.query(LessonPlan).order_by(LessonPlan.id).all()
        ],
        "activities": [
            {
                "id": activity.id,
                "lesson_plan_id": activity.lesson_plan_id,
                "title": activity.title,
                "description": activity.description,
                "sort_order": activity.sort_order,
                "is_required": activity.is_required,
            }
            for activity in db.query(Activity).order_by(Activity.id).all()
        ],
        "activity_completions": [
            {
                "id": completion.id,
                "activity_id": completion.activity_id,
                "student_id": completion.student_id,
                "completed": completion.completed,
                "completed_at": _serialize_datetime(completion.completed_at),
            }
            for completion in db.query(ActivityCompletion).order_by(ActivityCompletion.id).all()
        ],
        "school_day_years": [
            {
                "id": year.id,
                "teacher_id": year.teacher_id,
                "start_date": _serialize_date(year.start_date),
                "end_date": _serialize_date(year.end_date),
                "required_days": year.required_days,
                "created_at": _serialize_datetime(year.created_at),
                "updated_at": _serialize_datetime(year.updated_at),
            }
            for year in db.query(SchoolDayYear).order_by(SchoolDayYear.id).all()
        ],
        "approved_school_days": [
            {
                "id": day.id,
                "school_day_year_id": day.school_day_year_id,
                "day_date": _serialize_date(day.day_date),
                "approved_at": _serialize_datetime(day.approved_at),
            }
            for day in db.query(ApprovedSchoolDay).order_by(ApprovedSchoolDay.id).all()
        ],
    }
    return json.dumps(payload, indent=2).encode("utf-8")


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _validate_backup(data: dict[str, Any]) -> None:
    if data.get("version") != BACKUP_VERSION:
        raise ValueError("Unsupported backup file version.")
    for key in ("users", "lesson_plans", "activities", "activity_completions"):
        if key not in data or not isinstance(data[key], list):
            raise ValueError(f"Backup file is missing a valid '{key}' section.")
    for key in ("school_day_years", "approved_school_days"):
        if key in data and not isinstance(data[key], list):
            raise ValueError(f"Backup file is missing a valid '{key}' section.")


def import_database(db: Session, raw: bytes) -> None:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Backup file is not valid JSON.") from exc

    _validate_backup(data)

    db.query(ApprovedSchoolDay).delete()
    db.query(SchoolDayYear).delete()
    db.query(ActivityCompletion).delete()
    db.query(Activity).delete()
    db.query(LessonPlan).delete()
    db.query(User).delete()
    db.flush()

    for row in data["users"]:
        role_value = row["role"]
        if role_value == "administrator":
            role_value = "admin"
        db.add(
            User(
                id=row["id"],
                username=row["username"],
                email=row["email"],
                password_hash=row["password_hash"],
                role=UserRole(role_value),
                first_name=row["first_name"],
                last_name=row["last_name"],
                is_active=row["is_active"],
                created_at=_parse_datetime(row["created_at"]),
            )
        )

    for row in data["lesson_plans"]:
        db.add(
            LessonPlan(
                id=row["id"],
                title=row["title"],
                description=row.get("description"),
                plan_date=_parse_date(row["plan_date"]),
                teacher_id=row["teacher_id"],
                student_id=row["student_id"],
                created_at=_parse_datetime(row["created_at"]),
            )
        )

    for row in data["activities"]:
        db.add(
            Activity(
                id=row["id"],
                lesson_plan_id=row["lesson_plan_id"],
                title=row["title"],
                description=row.get("description"),
                sort_order=row["sort_order"],
                is_required=row["is_required"],
            )
        )

    for row in data["activity_completions"]:
        db.add(
            ActivityCompletion(
                id=row["id"],
                activity_id=row["activity_id"],
                student_id=row["student_id"],
                completed=row["completed"],
                completed_at=_parse_datetime(row.get("completed_at")),
            )
        )

    for row in data.get("school_day_years", []):
        db.add(
            SchoolDayYear(
                id=row["id"],
                teacher_id=row["teacher_id"],
                start_date=_parse_date(row["start_date"]),
                end_date=_parse_date(row["end_date"]),
                required_days=row["required_days"],
                created_at=_parse_datetime(row["created_at"]),
                updated_at=_parse_datetime(row.get("updated_at")),
            )
        )

    for row in data.get("approved_school_days", []):
        db.add(
            ApprovedSchoolDay(
                id=row["id"],
                school_day_year_id=row["school_day_year_id"],
                day_date=_parse_date(row["day_date"]),
                approved_at=_parse_datetime(row.get("approved_at")),
            )
        )

    db.flush()
    _reset_sequences(db)
    db.commit()


def _reset_sequences(db: Session) -> None:
    for table, column in (
        ("users", "id"),
        ("lesson_plans", "id"),
        ("activities", "id"),
        ("activity_completions", "id"),
        ("school_day_years", "id"),
        ("approved_school_days", "id"),
    ):
        db.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{table}', '{column}'), "
                f"COALESCE((SELECT MAX({column}) FROM {table}), 1))"
            )
        )
