from typing import ClassVar

from config.config import ServerConfig
from processing.base_parser import AbstractParser
from processing.parsers.docling_parser import DoclingParser


class ParserFactory:
    _parsers: ClassVar[dict[str, type[AbstractParser]]] = {
        "docling": DoclingParser,
    }

    @classmethod
    def create(
        cls,
        parser_type: str,
        server_config: ServerConfig,
    ) -> AbstractParser:
        parser_cls = cls._parsers.get(parser_type)

        if parser_cls is None:
            raise ValueError(f"Unsupported parser type: {parser_type}")

        return parser_cls(
            type=parser_type,
            server_config=server_config,
        )
