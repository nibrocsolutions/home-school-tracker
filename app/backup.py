import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import (
    Activity,
    ActivityCompletion,
    ActivityType,
    AppSetting,
    LessonPlan,
    PlannedSchoolDay,
    SchoolDayType,
    SchoolDayYear,
    User,
    UserRole,
    WeeklyScheduleItem,
    weekly_schedule_item_students,
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
                "age": user.age,
                "grade": user.grade,
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
                "is_sample_data": plan.is_sample_data,
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
                "activity_type": activity.activity_type.value,
                "audio_url": activity.audio_url,
                "teacher_notes": activity.teacher_notes,
                "external_link": activity.external_link,
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
                "student_message": completion.student_message,
                "message_read_at": _serialize_datetime(completion.message_read_at),
            }
            for completion in db.query(ActivityCompletion).order_by(ActivityCompletion.id).all()
        ],
        "app_settings": [
            {
                "id": setting.id,
                "sample_lesson_plans_enabled": setting.sample_lesson_plans_enabled,
                "sample_data_enabled": setting.sample_data_enabled,
                "updated_at": _serialize_datetime(setting.updated_at),
            }
            for setting in db.query(AppSetting).order_by(AppSetting.id).all()
        ],
        "weekly_schedule_items": [
            {
                "id": item.id,
                "teacher_id": item.teacher_id,
                "name": item.name,
                "item_kind": item.item_kind.value,
                "special_type": item.special_type.value if item.special_type else None,
                "weekdays": item.weekdays,
                "description": item.description,
                "external_link": item.external_link,
                "audio_url": item.audio_url,
                "sort_order": item.sort_order,
                "lesson_amount": item.lesson_amount,
                "include_numbering": item.include_numbering,
            }
            for item in db.query(WeeklyScheduleItem).order_by(WeeklyScheduleItem.id).all()
        ],
        "weekly_schedule_item_students": [
            {
                "schedule_item_id": row.schedule_item_id,
                "student_id": row.student_id,
            }
            for row in db.execute(
                text("SELECT schedule_item_id, student_id FROM weekly_schedule_item_students")
            ).fetchall()
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
        "planned_school_days": [
            {
                "id": day.id,
                "school_day_year_id": day.school_day_year_id,
                "day_date": _serialize_date(day.day_date),
                "day_type": day.day_type.value,
                "is_completed": day.is_completed,
                "updated_at": _serialize_datetime(day.updated_at),
            }
            for day in db.query(PlannedSchoolDay).order_by(PlannedSchoolDay.id).all()
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
    for key in ("school_day_years", "planned_school_days", "approved_school_days", "app_settings", "weekly_schedule_items", "weekly_schedule_item_students"):
        if key in data and not isinstance(data[key], list):
            raise ValueError(f"Backup file is missing a valid '{key}' section.")


def import_database(db: Session, raw: bytes) -> None:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Backup file is not valid JSON.") from exc

    _validate_backup(data)

    db.query(PlannedSchoolDay).delete()
    db.query(WeeklyScheduleItem).delete()
    db.query(SchoolDayYear).delete()
    db.query(AppSetting).delete()
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
                age=row.get("age"),
                grade=row.get("grade"),
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
                is_sample_data=row.get("is_sample_data", False),
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
                activity_type=ActivityType(row.get("activity_type", "regular")),
                audio_url=row.get("audio_url"),
                teacher_notes=row.get("teacher_notes"),
                external_link=row.get("external_link"),
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
                student_message=row.get("student_message"),
                message_read_at=_parse_datetime(row.get("message_read_at")),
            )
        )

    for row in data.get("app_settings", []):
        db.add(
            AppSetting(
                id=row["id"],
                sample_lesson_plans_enabled=row.get("sample_lesson_plans_enabled", False),
                sample_data_enabled=row.get("sample_data_enabled", False),
                updated_at=_parse_datetime(row.get("updated_at")),
            )
        )

    for row in data.get("weekly_schedule_items", []):
        from app.models import ScheduleItemKind, SpecialActivityKind
        from app.weekly_schedule import default_include_numbering

        special_type = row.get("special_type")
        item_kind = ScheduleItemKind(row["item_kind"])
        if "include_numbering" in row:
            include_numbering = bool(row.get("include_numbering"))
        else:
            include_numbering = default_include_numbering(row["name"], item_kind)
        db.add(
            WeeklyScheduleItem(
                id=row["id"],
                teacher_id=row["teacher_id"],
                name=row["name"],
                item_kind=item_kind,
                special_type=SpecialActivityKind(special_type) if special_type else None,
                weekdays=row["weekdays"],
                description=row.get("description"),
                external_link=row.get("external_link"),
                audio_url=row.get("audio_url"),
                sort_order=row.get("sort_order", 0),
                lesson_amount=row.get("lesson_amount", 0),
                include_numbering=include_numbering,
            )
        )

    for row in data.get("weekly_schedule_item_students", []):
        db.execute(
            weekly_schedule_item_students.insert().values(
                schedule_item_id=row["schedule_item_id"],
                student_id=row["student_id"],
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

    planned_rows = data.get("planned_school_days")
    if planned_rows is None:
        planned_rows = data.get("approved_school_days", [])

    for row in planned_rows:
        day_type_raw = row.get("day_type", "actual_school")
        if day_type_raw in ("skip", "sick"):
            day_type_raw = "school_off"
        try:
            day_type = SchoolDayType(day_type_raw)
        except ValueError:
            day_type = SchoolDayType.actual_school
        is_completed = row.get("is_completed", "approved_at" in row)
        updated_at = row.get("updated_at") or row.get("approved_at")
        db.add(
            PlannedSchoolDay(
                id=row["id"],
                school_day_year_id=row["school_day_year_id"],
                day_date=_parse_date(row["day_date"]),
                day_type=day_type,
                is_completed=is_completed,
                updated_at=_parse_datetime(updated_at),
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
        ("planned_school_days", "id"),
        ("app_settings", "id"),
        ("weekly_schedule_items", "id"),
    ):
        db.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{table}', '{column}'), "
                f"COALESCE((SELECT MAX({column}) FROM {table}), 1))"
            )
        )
