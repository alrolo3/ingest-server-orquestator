from __future__ import annotations

from dataclasses import dataclass
from os import getenv
from pathlib import Path

from queues.queue_local import LocalQueue


@dataclass(frozen=True, slots=True)
class ServerConfig:
    app_name: str
    environment: str
    inbound_queue_name: str
    chunk_max_tokens: int
    tokenizer_path: Path

_SERVER_CONFIG: ServerConfig | None = None


def load_server_config() -> ServerConfig | None:
    global _SERVER_CONFIG

    if _SERVER_CONFIG is None:
        _SERVER_CONFIG = ServerConfig(
            app_name=getenv("APP_NAME", "ingest-server-orquestator"),
            environment=getenv("APP_ENV", "local"),
            inbound_queue_name=getenv("INBOUND_QUEUE_NAME", "inbound"),
            chunk_max_tokens=int(getenv("CHUNK_MAX_TOKENS", "2048")),
            tokenizer_path=Path(getenv("TOKENIZER_PATH", "/datastore/models/tokenizers/qwen3-embedding-4b/")),
        )
        LocalQueue()

    return _SERVER_CONFIG


def get_server_config() -> ServerConfig | None:
    return load_server_config()
