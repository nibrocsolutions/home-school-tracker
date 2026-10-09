"""Auth helpers for machine-friendly backup export."""

from __future__ import annotations

import hmac
import os
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.auth import authenticate_user
from app.config import get_settings
from app.database import get_db
from app.models import UserRole


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


def _authenticate_admin_query(
    db: Session,
    username: str | None,
    password: str | None,
) -> None:
    """Validate admin credentials from query params."""
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Both user and pass query parameters are required.",
        )
    account = authenticate_user(db, username, password)
    if account is None or account.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials.",
        )


def require_backup_export_access(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: str | None = Query(default=None),
    password: str | None = Query(default=None, alias="pass"),
    authorization: str | None = Header(default=None),
    x_backup_token: str | None = Header(default=None, alias="X-Backup-Token"),
) -> bool:
    """Allow backup download via admin user/pass query params or shared token.

    Easy:   GET /api/backup/export?user=admin&pass=...
    Safer:  Authorization: Bearer <BACKUP_EXPORT_TOKEN>
    """
    if user is not None or password is not None:
        _authenticate_admin_query(db, user, password)
        return True

    expected = backup_export_token()
    if expected:
        provided = extract_backup_token(request, authorization, x_backup_token)
        if not provided or not hmac.compare_digest(provided, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing backup export token.",
            )
        return True

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=(
            "Provide admin user and pass query parameters, "
            "or configure BACKUP_EXPORT_TOKEN and send it as a Bearer token."
        ),
    )
