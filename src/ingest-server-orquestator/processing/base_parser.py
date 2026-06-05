from typing import Any

from pydantic import BaseModel, ConfigDict

from config.config import ServerConfig
from model.parsed_document import ParsedDocument
from queues.domain.job import Job


class AbstractParser(BaseModel):
    """Base interface for parser implementations."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: str
    server_config: ServerConfig

    def parse(self, source: Any) -> Any:
        raise NotImplementedError