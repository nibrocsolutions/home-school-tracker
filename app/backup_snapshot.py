"""Write rotated JSON backup snapshots for cron / ops use."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from app.backup import export_database
from app.database import SessionLocal


DEFAULT_BACKUP_DIR = Path(os.getenv("BACKUP_DIR") or (Path.cwd() / "backups"))
DEFAULT_KEEP = int(os.getenv("BACKUP_KEEP_COUNT") or "28")  # ~7 days at 4x/day


def backup_dir() -> Path:
    configured = (os.getenv("BACKUP_DIR") or "").strip()
    if configured:
        return Path(configured)
    return Path.cwd() / "backups"


def write_snapshot(
    *,
    output_dir: Path | None = None,
    keep_count: int | None = None,
    upload: bool = True,
) -> Path:
    """Export the database to a timestamped JSON file and optionally upload/rotate."""
    target_dir = output_dir or backup_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    destination = target_dir / f"hst-backup-{stamp}.json"

    db = SessionLocal()
    try:
        payload = export_database(db)
    finally:
        db.close()

    destination.write_bytes(payload)

    keep = DEFAULT_KEEP if keep_count is None else keep_count
    rotate_snapshots(target_dir, keep_count=keep)

    if upload:
        maybe_upload_snapshot(destination)

    return destination


def rotate_snapshots(target_dir: Path, *, keep_count: int) -> None:
    """Keep only the newest keep_count hst-backup-*.json files."""
    if keep_count <= 0:
        return
    files = sorted(
        target_dir.glob("hst-backup-*.json"),
        key=lambda path: path.name,
        reverse=True,
    )
    for stale in files[keep_count:]:
        try:
            stale.unlink()
        except OSError:
            continue


def maybe_upload_snapshot(snapshot_path: Path) -> None:
    """Optionally copy the snapshot to remote storage.

    Supported env vars:
    - BACKUP_S3_URI: e.g. s3://my-bucket/home-school-tracker/
      Uses `aws s3 cp` when available.
    - BACKUP_UPLOAD_CMD: custom shell command. `{path}` is replaced with the
      snapshot file path. Example:
      rclone copy '{path}' b2:homeschool-backups/
    """
    upload_cmd = (os.getenv("BACKUP_UPLOAD_CMD") or "").strip()
    if upload_cmd:
        command = upload_cmd.replace("{path}", str(snapshot_path))
        subprocess.run(command, shell=True, check=True)
        return

    s3_uri = (os.getenv("BACKUP_S3_URI") or "").strip()
    if not s3_uri:
        return

    aws = shutil.which("aws")
    if not aws:
        raise RuntimeError(
            "BACKUP_S3_URI is set but the AWS CLI (`aws`) was not found on PATH."
        )
    destination = s3_uri if s3_uri.endswith("/") else f"{s3_uri}/"
    subprocess.run(
        [aws, "s3", "cp", str(snapshot_path), destination],
        check=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Write a Home School Tracker JSON backup snapshot. "
            "Preferred for server-side cron (Raspberry Pi / Docker host)."
        )
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        help=f"Output directory (default: BACKUP_DIR or {DEFAULT_BACKUP_DIR})",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=None,
        help=f"How many snapshots to retain (default: BACKUP_KEEP_COUNT or {DEFAULT_KEEP})",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip optional S3/rclone upload even if configured",
    )
    args = parser.parse_args(argv)

    try:
        path = write_snapshot(
            output_dir=args.dir,
            keep_count=args.keep,
            upload=not args.no_upload,
        )
    except Exception as exc:  # noqa: BLE001 - CLI should print a clear error
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1

    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
