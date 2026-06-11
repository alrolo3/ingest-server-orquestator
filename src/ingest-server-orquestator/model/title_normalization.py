from pathlib import PurePosixPath
import re


_UPLOAD_UUID_PREFIX_RE = re.compile(
    r"^(?:"
    r"[0-9a-fA-F]{32}|"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r")-"
)
_DOCUMENT_EXTENSION_RE = re.compile(
    r"\.(?:pdf|docx?|pptx?|xlsx?|csv|rtf|txt|md|html?)$",
    re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"\s+")


def _sanitize_title_text(value: str) -> str:
    title = "".join(char if char.isalnum() else " " for char in value)
    return _WHITESPACE_RE.sub(" ", title).strip()


def normalize_document_title(
    value: str | None,
    *,
    strip_extension: bool = False,
) -> str | None:
    title = (value or "").strip()
    if not title:
        return None

    if strip_extension:
        title = PurePosixPath(title.replace("\\", "/")).name

    title = _UPLOAD_UUID_PREFIX_RE.sub("", title, count=1).strip()
    if strip_extension:
        title = _DOCUMENT_EXTENSION_RE.sub("", title).strip()

    title = _sanitize_title_text(title)
    return title or None
