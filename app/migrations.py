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
        for user in db.query(User).filter(User.username.in_(["student"])).all()
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
        if not _column_exists(inspector, "activities", "teacher_notes"):
            db.execute(text("ALTER TABLE activities ADD COLUMN teacher_notes TEXT"))
        if not _column_exists(inspector, "activities", "external_link"):
            db.execute(text("ALTER TABLE activities ADD COLUMN external_link VARCHAR(500)"))
        if not _column_exists(inspector, "activities", "media_attachments"):
            db.execute(text("ALTER TABLE activities ADD COLUMN media_attachments TEXT"))
            db.commit()
            # Move legacy single /media/... links into the multi-attachment field.
            db.execute(
                text(
                    "UPDATE activities "
                    "SET media_attachments = external_link, external_link = NULL "
                    "WHERE external_link IS NOT NULL "
                    "AND external_link LIKE '/media/%' "
                    "AND (media_attachments IS NULL OR media_attachments = '')"
                )
            )
            db.commit()

    if _table_exists(inspector, "activity_completions"):
        if not _column_exists(inspector, "activity_completions", "student_message"):
            db.execute(text("ALTER TABLE activity_completions ADD COLUMN student_message TEXT"))
        if not _column_exists(inspector, "activity_completions", "message_read_at"):
            db.execute(
                text("ALTER TABLE activity_completions ADD COLUMN message_read_at TIMESTAMP")
            )
            # Existing messages should not appear as unread after this feature ships.
            db.execute(
                text(
                    "UPDATE activity_completions "
                    "SET message_read_at = CURRENT_TIMESTAMP "
                    "WHERE student_message IS NOT NULL AND student_message != ''"
                )
            )

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

    if _table_exists(inspector, "weekly_schedule_items"):
        if not _column_exists(inspector, "weekly_schedule_items", "lesson_amount"):
            db.execute(
                text(
                    "ALTER TABLE weekly_schedule_items ADD COLUMN lesson_amount INTEGER "
                    "NOT NULL DEFAULT 0"
                )
            )
            db.commit()
        if not _column_exists(inspector, "weekly_schedule_items", "include_numbering"):
            db.execute(
                text(
                    "ALTER TABLE weekly_schedule_items ADD COLUMN include_numbering BOOLEAN "
                    "NOT NULL DEFAULT FALSE"
                )
            )
            db.commit()
            db.execute(
                text(
                    "UPDATE weekly_schedule_items "
                    "SET include_numbering = TRUE "
                    "WHERE item_kind = 'subject' "
                    "AND LOWER(name) IN ('math', 'language arts', 'history', 'science')"
                )
            )
            db.commit()
            inspector = inspect(db.get_bind())

    _migrate_weekly_schedule_item_students(db, inspector)
    _migrate_planned_school_days(db, inspector)
    _migrate_school_day_type_enum(db)
    _migrate_remove_skip_and_auto_holidays(db, inspector)
    _migrate_remove_sick_days(db, inspector)
    _migrate_holidays_to_days_off(db, inspector)
    _ensure_default_science_subject(db, inspect(db.get_bind()))


def _ensure_default_science_subject(db: Session, inspector) -> None:
    """Add the default Science subject for teachers who do not already have one."""
    if not _table_exists(inspector, "weekly_schedule_items"):
        return
    if not _column_exists(inspector, "weekly_schedule_items", "include_numbering"):
        return

    from app.models import ScheduleItemKind, User, UserRole, WeeklyScheduleItem

    teachers = (
        db.query(User)
        .filter(User.role == UserRole.teacher, User.is_active.is_(True))
        .all()
    )
    if not teachers:
        return

    students = (
        db.query(User)
        .filter(User.role == UserRole.student, User.is_active.is_(True))
        .all()
    )

    changed = False
    for teacher in teachers:
        existing = (
            db.query(WeeklyScheduleItem)
            .filter(
                WeeklyScheduleItem.teacher_id == teacher.id,
                WeeklyScheduleItem.item_kind == ScheduleItemKind.subject,
                WeeklyScheduleItem.name.ilike("science"),
            )
            .first()
        )
        if existing:
            continue

        max_order = (
            db.query(WeeklyScheduleItem)
            .filter(WeeklyScheduleItem.teacher_id == teacher.id)
            .count()
        )
        science = WeeklyScheduleItem(
            teacher_id=teacher.id,
            name="Science",
            item_kind=ScheduleItemKind.subject,
            special_type=None,
            weekdays="",
            description="Hands-on experiments, observations, and science workbook lessons.",
            lesson_amount=120,
            include_numbering=True,
            sort_order=max_order + 1,
        )
        if students:
            science.assigned_students = list(students)
        db.add(science)
        changed = True

    if changed:
        db.commit()


def _migrate_school_day_type_enum(db: Session) -> None:
    """Ensure legacy sick label exists on PostgreSQL enums so rows can be rewritten."""
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return

    db.commit()
    rows = db.execute(
        text(
            "SELECT DISTINCT t.typname "
            "FROM pg_type t "
            "JOIN pg_enum e ON t.oid = e.enumtypid "
            "WHERE e.enumlabel = 'actual_school'"
        )
    ).fetchall()
    type_names = {row[0] for row in rows}
    if not type_names:
        return

    raw = bind.execution_options(isolation_level="AUTOCOMMIT")
    with raw.connect() as conn:
        for type_name in type_names:
            for value in ("sick",):
                exists = conn.execute(
                    text(
                        "SELECT 1 FROM pg_enum e "
                        "JOIN pg_type t ON t.oid = e.enumtypid "
                        "WHERE t.typname = :type_name AND e.enumlabel = :value"
                    ),
                    {"type_name": type_name, "value": value},
                ).first()
                if exists:
                    continue
                conn.execute(text(f"ALTER TYPE {type_name} ADD VALUE '{value}'"))


def _migrate_remove_sick_days(db: Session, inspector) -> None:
    """Convert any remaining sick days to school_off (days off)."""
    if not _table_exists(inspector, "planned_school_days"):
        return

    bind = db.get_bind()
    # On PostgreSQL, comparing to a missing enum label raises InvalidTextRepresentation.
    if bind.dialect.name == "postgresql" and not _enum_has_label(db, "sick"):
        return

    db.execute(
        text(
            "UPDATE planned_school_days "
            "SET day_type = 'school_off' "
            "WHERE day_type = 'sick'"
        )
    )
    db.commit()


def _migrate_holidays_to_days_off(db: Session, inspector) -> None:
    """Holiday is no longer a day-kind choice; convert remaining holidays to days off."""
    if not _table_exists(inspector, "planned_school_days"):
        return

    bind = db.get_bind()
    if bind.dialect.name == "postgresql" and not _enum_has_label(db, "holiday"):
        return

    db.execute(
        text(
            "UPDATE planned_school_days "
            "SET day_type = 'school_off' "
            "WHERE day_type = 'holiday'"
        )
    )
    db.commit()


def _enum_has_label(db: Session, label: str) -> bool:
    """Return True if the planned_school_days day_type enum includes the given label."""
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return True

    row = db.execute(
        text(
            "SELECT 1 "
            "FROM pg_enum e "
            "JOIN pg_type t ON t.oid = e.enumtypid "
            "JOIN information_schema.columns c "
            "  ON c.udt_name = t.typname "
            "WHERE c.table_name = 'planned_school_days' "
            "  AND c.column_name = 'day_type' "
            "  AND e.enumlabel = :label "
            "LIMIT 1"
        ),
        {"label": label},
    ).first()
    if row:
        return True

    # Fallback for atypical type naming.
    row = db.execute(
        text(
            "SELECT 1 FROM pg_enum e "
            "JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname ILIKE '%schooldaytype%' AND e.enumlabel = :label "
            "LIMIT 1"
        ),
        {"label": label},
    ).first()
    return row is not None


def _migrate_remove_skip_and_auto_holidays(db: Session, inspector) -> None:
    """Convert skip days to school_off; one-time reset of auto-applied holidays."""
    if not _table_exists(inspector, "planned_school_days"):
        return

    # Only rewrite skip rows when the DB enum actually contains 'skip'.
    # Fresh installs never added that label, and comparing to it raises InvalidTextRepresentation.
    if _enum_has_label(db, "skip"):
        db.execute(
            text(
                "UPDATE planned_school_days "
                "SET day_type = 'school_off' "
                "WHERE day_type = 'skip'"
            )
        )
        db.commit()

    if not _table_exists(inspector, "app_settings"):
        return

    if not _column_exists(inspector, "app_settings", "cleared_auto_holidays"):
        db.execute(
            text(
                "ALTER TABLE app_settings "
                "ADD COLUMN cleared_auto_holidays BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        db.commit()
        inspector = inspect(db.get_bind())

    settings = db.query(AppSetting).first()
    if settings is None:
        settings = AppSetting(
            sample_lesson_plans_enabled=False,
            sample_data_enabled=False,
            cleared_auto_holidays=False,
        )
        db.add(settings)
        db.flush()

    if settings.cleared_auto_holidays:
        return

    # Federal holidays were previously auto-marked; reset once so lessons can use them
    # unless the teacher later marks a day as holiday manually.
    db.execute(
        text(
            "UPDATE planned_school_days "
            "SET day_type = 'actual_school' "
            "WHERE day_type = 'holiday'"
        )
    )
    settings.cleared_auto_holidays = True
    db.commit()


def _migrate_weekly_schedule_item_students(db: Session, inspector) -> None:
    if not _table_exists(inspector, "weekly_schedule_items"):
        return

    if not _table_exists(inspector, "weekly_schedule_item_students"):
        db.execute(
            text(
                "CREATE TABLE weekly_schedule_item_students ("
                "schedule_item_id INTEGER NOT NULL, "
                "student_id INTEGER NOT NULL, "
                "PRIMARY KEY (schedule_item_id, student_id), "
                "FOREIGN KEY(schedule_item_id) REFERENCES weekly_schedule_items (id) ON DELETE CASCADE, "
                "FOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE"
                ")"
            )
        )
        db.commit()
        inspector = inspect(db.get_bind())

    if not _table_exists(inspector, "weekly_schedule_item_students"):
        return

    existing_links = db.execute(
        text("SELECT COUNT(*) FROM weekly_schedule_item_students")
    ).scalar()
    if existing_links:
        return

    student_ids = [
        row[0]
        for row in db.execute(
            text("SELECT id FROM users WHERE role = 'student' AND is_active = TRUE")
        ).fetchall()
    ]
    if not student_ids:
        return

    schedule_item_ids = [
        row[0] for row in db.execute(text("SELECT id FROM weekly_schedule_items")).fetchall()
    ]
    for schedule_item_id in schedule_item_ids:
        for student_id in student_ids:
            db.execute(
                text(
                    "INSERT INTO weekly_schedule_item_students "
                    "(schedule_item_id, student_id) VALUES (:schedule_item_id, :student_id)"
                ),
                {"schedule_item_id": schedule_item_id, "student_id": student_id},
            )
    db.commit()


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
