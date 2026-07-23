"""Central media library for lesson attachments (audio, PDFs, and other files)."""

from __future__ import annotations

import mimetypes
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

MEDIA_URL_PREFIX = "/media"

# Suggested top-level folders for organizing lesson files.
DEFAULT_MEDIA_FOLDERS = (
    "history",
    "math",
    "language-arts",
    "science",
    "other",
)

AUDIO_EXTENSIONS = frozenset({".mp3", ".m4a", ".wav", ".ogg", ".aac", ".flac", ".wma"})
DOCUMENT_EXTENSIONS = frozenset({".pdf", ".txt", ".doc", ".docx", ".epub", ".rtf"})
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".webm", ".mov", ".m4v"})

ALLOWED_UPLOAD_EXTENSIONS = (
    AUDIO_EXTENSIONS
    | DOCUMENT_EXTENSIONS
    | IMAGE_EXTENSIONS
    | VIDEO_EXTENSIONS
    | {".zip", ".csv", ".json", ".md"}
)

# Audiobook chapters can be large; keep a generous but finite ceiling.
MAX_UPLOAD_BYTES = int(os.getenv("MEDIA_MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))
FOLDER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
UNSAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._()\[\]\-\s]+")


@dataclass(frozen=True)
class MediaFile:
    relative_path: str
    name: str
    size: int
    kind: str
    url: str
    folder: str


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


def ensure_default_media_folders() -> list[str]:
    """Create the standard subject subfolders under the media root."""
    root = media_root()
    created: list[str] = []
    for name in DEFAULT_MEDIA_FOLDERS:
        folder = root / name
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
            created.append(name)
        else:
            folder.mkdir(parents=True, exist_ok=True)
    return created


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


def is_audio_media_url(value: str | None) -> bool:
    if not value:
        return False
    lower = value.strip().lower()
    return any(lower.endswith(ext) for ext in AUDIO_EXTENSIONS)


def parse_media_attachments(value: str | None) -> list[str]:
    """Parse stored media attachments (newline or comma separated /media URLs)."""
    if not value:
        return []
    urls: list[str] = []
    seen: set[str] = set()
    for raw_line in value.replace(",", "\n").splitlines():
        item = raw_line.strip()
        if not item:
            continue
        if not is_media_library_url(item):
            # Allow relative library paths too.
            if item.startswith("/"):
                continue
            item = media_url_for(item)
        if item in seen:
            continue
        seen.add(item)
        urls.append(item)
    return urls


def serialize_media_attachments(urls: list[str] | None) -> str | None:
    cleaned = parse_media_attachments("\n".join(urls or []))
    if not cleaned:
        return None
    return "\n".join(cleaned)


def activity_media_urls(
    *,
    media_attachments: str | None = None,
    external_link: str | None = None,
    audio_url: str | None = None,
) -> list[str]:
    """Collect media library URLs for an activity, including legacy single-link fields."""
    urls = parse_media_attachments(media_attachments)
    seen = set(urls)
    for candidate in (external_link, audio_url):
        text = (candidate or "").strip()
        if not text or not is_media_library_url(text):
            continue
        if text in seen:
            continue
        seen.add(text)
        urls.append(text)
    return urls


def activity_external_web_link(external_link: str | None) -> str | None:
    """Return external_link only when it is a non-media web URL."""
    text = (external_link or "").strip()
    if not text or is_media_library_url(text):
        return None
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


def _folder_for_relative(relative: str) -> str:
    parts = Path(relative).parts
    if len(parts) > 1:
        return parts[0]
    return "(root)"


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


def list_media_files(
    *,
    query: str | None = None,
    folder: str | None = None,
) -> list[MediaFile]:
    """List files under the media root (recursive), optionally filtered by folder/search."""
    ensure_default_media_folders()
    root = media_root()
    needle = (query or "").strip().lower()
    folder_filter = (folder or "").strip().strip("/")
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
        folder_name = _folder_for_relative(relative)
        if folder_filter:
            if folder_filter == "(root)":
                if "/" in relative:
                    continue
            elif folder_name != folder_filter:
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
                folder=folder_name,
            )
        )

    results.sort(key=lambda item: item.relative_path.lower())
    return results


def list_media_folders() -> list[dict]:
    """Return top-level folders (including empty default folders) with file counts."""
    ensure_default_media_folders()
    root = media_root()
    counts: dict[str, int] = {name: 0 for name in DEFAULT_MEDIA_FOLDERS}
    root_count = 0

    for path in root.iterdir():
        if path.is_dir() and not path.name.startswith("."):
            counts.setdefault(path.name, 0)

    for item in list_media_files():
        if item.folder == "(root)":
            root_count += 1
        else:
            counts[item.folder] = counts.get(item.folder, 0) + 1

    folders = [
        {"name": name, "path": name, "file_count": counts.get(name, 0)}
        for name in sorted(counts.keys(), key=str.lower)
    ]
    if root_count:
        folders.insert(0, {"name": "(root)", "path": "(root)", "file_count": root_count})
    return folders


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
    ensure_default_media_folders()
    files = list_media_files()
    folders = list_media_folders()
    return {
        "root": str(media_root()),
        "file_count": len(files),
        "folder_count": len([f for f in folders if f["path"] != "(root)"]),
        "folders": [f["path"] for f in folders if f["path"] != "(root)"],
        "folder_details": folders,
        "files": [
            {
                "path": item.relative_path,
                "name": item.name,
                "size": item.size,
                "size_label": format_file_size(item.size),
                "kind": item.kind,
                "url": item.url,
                "folder": item.folder,
            }
            for item in files
        ],
    }


def sanitize_upload_filename(filename: str) -> str:
    """Return a safe basename for an uploaded file."""
    base = Path(filename or "").name.strip()
    base = unicodedata.normalize("NFKC", base)
    base = UNSAFE_FILENAME_RE.sub("_", base).strip(" .")
    if not base or base in {".", ".."}:
        raise ValueError("Please choose a valid file name.")
    if Path(base).suffix.lower() not in ALLOWED_UPLOAD_EXTENSIONS:
        raise ValueError(
            "That file type is not allowed. Use audio, PDF, image, video, or common document files."
        )
    return base


def resolve_upload_folder(folder_name: str) -> Path:
    """Resolve/create a top-level media folder for uploads."""
    ensure_default_media_folders()
    cleaned = (folder_name or "").strip().strip("/\\")
    if not cleaned or cleaned == "(root)":
        cleaned = "other"
    if not FOLDER_NAME_RE.fullmatch(cleaned):
        raise ValueError("Choose a valid media folder name.")
    if ".." in cleaned or "/" in cleaned or "\\" in cleaned:
        raise ValueError("Choose a valid media folder name.")

    root = media_root()
    target = (root / cleaned).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("Choose a valid media folder name.") from exc
    target.mkdir(parents=True, exist_ok=True)
    if not target.is_dir():
        raise ValueError("That media folder could not be used.")
    return target


def unique_destination(folder: Path, filename: str) -> Path:
    """Avoid overwriting existing files by appending -2, -3, ... as needed."""
    dest = folder / filename
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    index = 2
    while True:
        candidate = folder / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def save_uploaded_media_file(
    *,
    folder_name: str,
    filename: str,
    content: bytes,
) -> MediaFile:
    """Validate and write an uploaded file into the media library."""
    if not content:
        raise ValueError("The selected file was empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"That file is too large. Maximum size is {format_file_size(MAX_UPLOAD_BYTES)}."
        )

    safe_name = sanitize_upload_filename(filename)
    folder = resolve_upload_folder(folder_name)
    destination = unique_destination(folder, safe_name)
    destination.write_bytes(content)

    relative = destination.relative_to(media_root()).as_posix()
    return MediaFile(
        relative_path=relative,
        name=destination.name,
        size=len(content),
        kind=_file_kind(destination),
        url=media_url_for(relative),
        folder=_folder_for_relative(relative),
    )
