"""Token helpers for machine-friendly backup export."""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException, Request, status

from app.config import get_settings


def backup_export_token() -> str:
    return (get_settings().backup_export_token or os.getenv("BACKUP_EXPORT_TOKEN") or "").strip()


def extract_backup_token(
    request: Request,
    authorization: str | None = None,
    x_backup_token: str | None = None,
) -> str | None:
    if x_backup_token and x_backup_token.strip():
        return x_backup_token.strip()
    header = authorization or request.headers.get("Authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def require_backup_export_token(
    request: Request,
    authorization: str | None = Header(default=None),
    x_backup_token: str | None = Header(default=None, alias="X-Backup-Token"),
) -> None:
    """Allow cron/curl access when BACKUP_EXPORT_TOKEN is configured."""
    expected = backup_export_token()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Backup export token is not configured on the server.",
        )
    provided = extract_backup_token(request, authorization, x_backup_token)
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing backup export token.",
        )
    return True
