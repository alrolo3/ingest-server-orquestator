from typing import Any

from docling_core.types import DoclingDocument
from pydantic import BaseModel


class AbstractOutputDocument(BaseModel):
    raw: Any


class DoclingOutputDocument(AbstractOutputDocument):
    raw: DoclingDocument  # DoclingDocument
