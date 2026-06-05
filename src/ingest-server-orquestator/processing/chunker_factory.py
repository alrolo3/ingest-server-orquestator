from typing import ClassVar

from config.config import ServerConfig
from processing.base_chunker import AbstractChunker
from processing.chunking.docling_chunker import DoclingChunker


class ChunkerFactory:
    _chunkers: ClassVar[dict[str, type[AbstractChunker]]] = {
        "docling": DoclingChunker,
    }

    @classmethod
    def create(
        cls,
        chunker_backend: str,
        chunker_type: str,
        server_config: ServerConfig,
        tokenizer_path: str,
    ) -> AbstractChunker:
        chunker_cls = cls._chunkers.get(chunker_backend)

        if chunker_cls is None:
            raise ValueError(f"Unsupported chunker backend: {chunker_backend}")

        return chunker_cls(
            type=chunker_type,
            server_config=server_config,
            tokenizer_path=tokenizer_path,
        )