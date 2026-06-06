from pydantic import BaseModel, ConfigDict

from config.config import ServerConfig
from metrics.progress import ProgressReporter
from model.document_chunk import DocumentChunk
from model.parsed_document import ParsedDocument


class AbstractChunker(BaseModel):
    """Base interface for chunker implementations."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: str
    server_config: ServerConfig

    def chunk(self, doc: ParsedDocument, progress: ProgressReporter) -> list[DocumentChunk]:
        raise NotImplementedError
