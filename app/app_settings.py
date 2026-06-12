from sqlalchemy.orm import Session

from app.models import AppSetting


def get_app_settings(db: Session) -> AppSetting:
    settings = db.query(AppSetting).first()
    if not settings:
        settings = AppSetting(sample_lesson_plans_enabled=False, sample_data_enabled=False)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def sample_lesson_plans_enabled(db: Session) -> bool:
    return get_app_settings(db).sample_lesson_plans_enabled


def sample_data_enabled(db: Session) -> bool:
    return get_app_settings(db).sample_data_enabled
