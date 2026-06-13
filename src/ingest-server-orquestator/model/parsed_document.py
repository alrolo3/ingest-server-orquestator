from typing import Any

from pydantic import BaseModel, Field

from model.base_document import AbstractOutputDocument


class ParsedDocument(BaseModel):
    document_id: str
    source_file_name: str
    source_path: str
    collection_name: str | None = None
    task_id: str | None = None
    source_size_bytes: int | None = None
    mime_type: str | None = None
    title: str | None = None
    page_count: int = 0
    #pages: list[DocumentPage] = Field(default_factory=list)
    #elements: list[DocumentElement] = Field(default_factory=list)
    markdown: str = ""
    text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    original_out_doc: AbstractOutputDocument

    def get_markdown(self) -> str:
        """Return the normalized output as Markdown string.SOLO DOCLING"""
        return self.original_out_doc.raw.export_to_markdown()
