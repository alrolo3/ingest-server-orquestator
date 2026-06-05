from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    content: str
    document_id: str
    chunk_id: str
    chunk_index: int
    chunking_strategy: str
    content_token_count: int | None = None
    doc_items: list[str] = Field(default_factory=list)
    page_number: int | None = None
    page_numbers: list[int] = Field(default_factory=list)
    total_pages: int = 0
    title: str | None = None
    source_file_name: str = ""
    raw_text: str | None = None
