from typing import Any

from docling_core.types import DoclingDocument
from pydantic import BaseModel


class AbstractOutputDocument(BaseModel):
    """Wrapper for parser-native output documents stored beside normalized metadata."""

    raw: Any


class DoclingOutputDocument(AbstractOutputDocument):
    """Typed wrapper around DoclingDocument so downstream code can call Docling APIs."""

    raw: DoclingDocument  # DoclingDocument
