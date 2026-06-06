from pydantic import BaseModel, ConfigDict

from model.document_chunk import DocumentChunk


class AbstractDispatcher(BaseModel):
    """Base interface for outbound dispatchers."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def dispatch_chunks(self, chunks: list[DocumentChunk]) -> None:
        raise NotImplementedError

    def dispatch_markdown(self, markdown: str) -> None:
        raise NotImplementedError
