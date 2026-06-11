import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    teacher = "teacher"
    student = "student"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), index=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
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

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class LessonPlan(Base):
    __tablename__ = "lesson_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_date: Mapped[date] = mapped_column(Date, index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
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

    activity: Mapped["Activity"] = relationship("Activity", back_populates="completions")
    student: Mapped["User"] = relationship("User", back_populates="activity_completions")
