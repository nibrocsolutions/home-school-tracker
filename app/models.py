import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    teacher = "teacher"
    student = "student"


class ActivityType(str, enum.Enum):
    regular = "regular"
    special = "special"
    subject = "subject"
    history = "history"


class SpecialActivityKind(str, enum.Enum):
    co_op = "co_op"
    wild_and_free = "wild_and_free"
    classical_conversations = "classical_conversations"
    other = "other"


class ScheduleItemKind(str, enum.Enum):
    special_activity = "special_activity"
    subject = "subject"


weekly_schedule_item_students = Table(
    "weekly_schedule_item_students",
    Base.metadata,
    Column(
        "schedule_item_id",
        Integer,
        ForeignKey("weekly_schedule_items.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "student_id",
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), index=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grade: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lesson_plans_taught: Mapped[list["LessonPlan"]] = relationship(
        "LessonPlan", back_populates="teacher", foreign_keys="LessonPlan.teacher_id"
    )
    lesson_plans_assigned: Mapped[list["LessonPlan"]] = relationship(
        "LessonPlan", back_populates="student", foreign_keys="LessonPlan.student_id"
    )
    activity_completions: Mapped[list["ActivityCompletion"]] = relationship(
        "ActivityCompletion", back_populates="student"
    )
    school_day_years: Mapped[list["SchoolDayYear"]] = relationship(
        "SchoolDayYear", back_populates="teacher"
    )
    weekly_schedule_items: Mapped[list["WeeklyScheduleItem"]] = relationship(
        "WeeklyScheduleItem", back_populates="teacher"
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def grade_age_label(self) -> str | None:
        parts = []
        if self.grade:
            parts.append(self.grade)
        if self.age is not None:
            parts.append(f"Age {self.age}")
        return " · ".join(parts) if parts else None


class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sample_lesson_plans_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sample_data_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    cleared_auto_holidays: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class WeeklyScheduleItem(Base):
    __tablename__ = "weekly_schedule_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(120))
    item_kind: Mapped[ScheduleItemKind] = mapped_column(Enum(ScheduleItemKind))
    special_type: Mapped[SpecialActivityKind | None] = mapped_column(
        Enum(SpecialActivityKind), nullable=True
    )
    weekdays: Mapped[str] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    audio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    lesson_amount: Mapped[int] = mapped_column(Integer, default=0)
    include_numbering: Mapped[bool] = mapped_column(Boolean, default=False)

    teacher: Mapped["User"] = relationship("User", back_populates="weekly_schedule_items")
    assigned_students: Mapped[list["User"]] = relationship(
        "User",
        secondary=weekly_schedule_item_students,
    )


class LessonPlan(Base):
    __tablename__ = "lesson_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_date: Mapped[date] = mapped_column(Date, index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    is_sample_data: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    teacher: Mapped["User"] = relationship(
        "User", back_populates="lesson_plans_taught", foreign_keys=[teacher_id]
    )
    student: Mapped["User"] = relationship(
        "User", back_populates="lesson_plans_assigned", foreign_keys=[student_id]
    )
    activities: Mapped[list["Activity"]] = relationship(
        "Activity", back_populates="lesson_plan", cascade="all, delete-orphan"
    )


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    lesson_plan_id: Mapped[int] = mapped_column(ForeignKey("lesson_plans.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)
    activity_type: Mapped[ActivityType] = mapped_column(
        Enum(ActivityType), default=ActivityType.regular
    )
    audio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    teacher_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    media_attachments: Mapped[str | None] = mapped_column(Text, nullable=True)

    lesson_plan: Mapped["LessonPlan"] = relationship("LessonPlan", back_populates="activities")
    completions: Mapped[list["ActivityCompletion"]] = relationship(
        "ActivityCompletion", back_populates="activity", cascade="all, delete-orphan"
    )


class ActivityCompletion(Base):
    __tablename__ = "activity_completions"
    __table_args__ = (UniqueConstraint("activity_id", "student_id", name="uq_activity_student"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    student_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    activity: Mapped["Activity"] = relationship("Activity", back_populates="completions")
    student: Mapped["User"] = relationship("User", back_populates="activity_completions")


class SchoolDayType(str, enum.Enum):
    actual_school = "actual_school"
    school_off = "school_off"
    holiday = "holiday"
    weekend = "weekend"


class SchoolDayYear(Base):
    __tablename__ = "school_day_years"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    required_days: Mapped[int] = mapped_column(Integer, default=180)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    teacher: Mapped["User"] = relationship("User", back_populates="school_day_years")
    planned_days: Mapped[list["PlannedSchoolDay"]] = relationship(
        "PlannedSchoolDay", back_populates="school_day_year", cascade="all, delete-orphan"
    )


class PlannedSchoolDay(Base):
    __tablename__ = "planned_school_days"
    __table_args__ = (
        UniqueConstraint("school_day_year_id", "day_date", name="uq_school_day_year_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    school_day_year_id: Mapped[int] = mapped_column(ForeignKey("school_day_years.id"))
    day_date: Mapped[date] = mapped_column(Date, index=True)
    day_type: Mapped[SchoolDayType] = mapped_column(
        Enum(SchoolDayType), default=SchoolDayType.actual_school
    )
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    school_day_year: Mapped["SchoolDayYear"] = relationship(
        "SchoolDayYear", back_populates="planned_days"
    )
