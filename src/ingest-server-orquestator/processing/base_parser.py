from pydantic import BaseModel, ConfigDict

from config.config import ServerConfig
from metrics.progress import ProgressReporter
from model.parsed_document import ParsedDocument
from queues.domain.job import Job


class AbstractParser(BaseModel):
    """Base interface for parser implementations."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: str
    server_config: ServerConfig

    def parse(self, job: Job, progress: ProgressReporter) -> ParsedDocument:
        raise NotImplementedError
