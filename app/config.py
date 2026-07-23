import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    app_name: str = "Home School Tracker"
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-change-in-production")
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://hst_user:change_me_secure_password@db:5432/home_school_tracker",
    )
    access_token_expire_minutes: int = 60 * 12
    algorithm: str = "HS256"
    media_root: str = os.getenv("MEDIA_ROOT", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
