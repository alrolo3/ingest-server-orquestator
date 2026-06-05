from abc import ABC, abstractmethod
from typing import Any

from docling_core.types import DoclingDocument
from pydantic import BaseModel, ConfigDict

from config.config import ServerConfig
from model.document_chunk import DocumentChunk
from model.parsed_document import ParsedDocument


class AbstractChunker(BaseModel):
    """Base interface for chunker implementations."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: str
    server_config: ServerConfig

    def chunk(self, doc: ParsedDocument) -> list[DocumentChunk]:
        raise NotImplementedError