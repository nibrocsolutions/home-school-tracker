"""Central media library for lesson attachments (audio, PDFs, and other files)."""

from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path

MEDIA_URL_PREFIX = "/media"

AUDIO_EXTENSIONS = frozenset({".mp3", ".m4a", ".wav", ".ogg", ".aac", ".flac", ".wma"})
DOCUMENT_EXTENSIONS = frozenset({".pdf", ".txt", ".doc", ".docx", ".epub", ".rtf"})
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".webm", ".mov", ".m4v"})


@dataclass(frozen=True)
class MediaFile:
    relative_path: str
    name: str
    size: int
    kind: str
    url: str


def media_root() -> Path:
    """Return the on-disk media library folder (created if missing)."""
    configured = (os.getenv("MEDIA_ROOT") or "").strip()
    if configured:
        root = Path(configured)
    else:
        # Prefer /app/media in containers; fall back to repo-local ./media.
        container_default = Path("/app/media")
        if container_default.parent.exists():
            root = container_default
        else:
            root = Path.cwd() / "media"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def media_url_for(relative_path: str) -> str:
    cleaned = relative_path.replace("\\", "/").lstrip("/")
    return f"{MEDIA_URL_PREFIX}/{cleaned}"


def is_media_library_url(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().startswith(f"{MEDIA_URL_PREFIX}/")


def media_display_name(value: str | None) -> str:
    if not value:
        return ""
    text = value.strip()
    if is_media_library_url(text):
        return text[len(MEDIA_URL_PREFIX) + 1 :]
    return text


def _file_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in DOCUMENT_EXTENSIONS:
        return "document"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return "file"


def resolve_media_file(relative_path: str) -> Path | None:
    """Resolve a relative library path safely (blocks path traversal)."""
    if not relative_path or relative_path.strip() != relative_path:
        return None
    cleaned = relative_path.replace("\\", "/").lstrip("/")
    if not cleaned or ".." in Path(cleaned).parts:
        return None

    root = media_root()
    candidate = (root / cleaned).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def guess_media_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def list_media_files(*, query: str | None = None) -> list[MediaFile]:
    """List all files under the media root (recursive), newest folders first by path."""
    root = media_root()
    needle = (query or "").strip().lower()
    results: list[MediaFile] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        if path.name.upper() == "README.MD":
            continue
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if needle and needle not in relative.lower() and needle not in path.name.lower():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        results.append(
            MediaFile(
                relative_path=relative,
                name=path.name,
                size=size,
                kind=_file_kind(path),
                url=media_url_for(relative),
            )
        )

    results.sort(key=lambda item: item.relative_path.lower())
    return results


def format_file_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


def media_library_summary() -> dict:
    files = list_media_files()
    folders = sorted(
        {
            Path(item.relative_path).parts[0]
            for item in files
            if "/" in item.relative_path
        }
    )
    return {
        "root": str(media_root()),
        "file_count": len(files),
        "folder_count": len(folders),
        "folders": folders,
        "files": [
            {
                "path": item.relative_path,
                "name": item.name,
                "size": item.size,
                "size_label": format_file_size(item.size),
                "kind": item.kind,
                "url": item.url,
            }
            for item in files
        ],
    }
