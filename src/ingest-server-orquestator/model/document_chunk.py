from typing import Any

from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    content: str
    content_dense: str | None = None
    content_sparse: str
    document_id: str
    chunk_id: str
    chunk_index: int
    chunking_strategy: str
    collection_name: str | None = None
    task_id: str | None = None
    source_size_bytes: int | None = None
    content_token_count: int | None = None
    doc_items: list[str] = Field(default_factory=list)
    page_number: int | None = None
    page_numbers: list[int] = Field(default_factory=list)
    total_pages: int = 0
    title: str | None = None
    clean_title: str | None = None
    headings: list[str] = Field(default_factory=list)
    source_file_name: str = ""
    document_metadata: dict[str, Any] = Field(default_factory=dict)
