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
    r"\.(?:pdf|docx?|pptx?|xlsx?|txt|md|html?)$",
    re.IGNORECASE,
)


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

    return title or None
