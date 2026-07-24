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
    # Shared secret for cron/curl backup downloads (optional).
    backup_export_token: str = os.getenv("BACKUP_EXPORT_TOKEN", "")
    backup_dir: str = os.getenv("BACKUP_DIR", "")
    backup_keep_count: int = int(os.getenv("BACKUP_KEEP_COUNT") or "28")
    backup_s3_uri: str = os.getenv("BACKUP_S3_URI", "")
    backup_upload_cmd: str = os.getenv("BACKUP_UPLOAD_CMD", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
