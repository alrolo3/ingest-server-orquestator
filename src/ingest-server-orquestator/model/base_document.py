from abc import abstractmethod, ABC
from dataclasses import dataclass
from typing import Any

from docling_core.types import DoclingDocument
from pydantic import BaseModel


class AbstractOutputDocument(BaseModel):
    raw: Any
    pass


class DoclingOutputDocument(AbstractOutputDocument):
    raw: DoclingDocument  # DoclingDocument


class MinerUOutputDocument(AbstractOutputDocument):
    raw: Any  # MinerU document/result