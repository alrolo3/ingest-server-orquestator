from __future__ import annotations

from dataclasses import dataclass, field
from os import getenv
from pathlib import Path

from queues.queue_local import LocalQueue


_DEFAULT_ELASTIC_HOSTS = ["https://localhost:9200"]
_DEFAULT_ELASTIC_API_KEY = (
    "RW9RbG1aNEJ4QVZwbFVaNjNhOEc6QTY1b1V2cDU4MUUxWHZjeTkxTkx4UQ=="
)
_DEFAULT_ELASTIC_INFERENCE_ID = "qwen3-embedding-4b"
_FALSE_VALUES = {"", "0", "false", "no", "off"}


def _default_elastic_hosts() -> list[str]:
    return list(_DEFAULT_ELASTIC_HOSTS)


@dataclass(frozen=True, slots=True)
class ServerConfig:
    app_name: str
    environment: str
    inbound_queue_name: str
    chunk_max_tokens: int
    tokenizer_path: Path
    cuda_device_order: str = "PCI_BUS_ID"
    physical_cuda_device: str = "4"
    visible_cuda_devices: str = "0"
    logical_cuda_device_index: int = 0
    docling_device: str = "cuda:0"
    elastic_hosts: list[str] = field(default_factory=_default_elastic_hosts)
    elastic_api_key: str | None = _DEFAULT_ELASTIC_API_KEY
    elastic_index_name: str = "open-rag-embeddings-v3"
    elastic_pipeline_name: str = "open_rag_embeddings_v3_multilingual_semantic_pipeline"
    elastic_inference_id: str = _DEFAULT_ELASTIC_INFERENCE_ID
    elastic_verify_certs: bool = False
    elastic_ssl_show_warn: bool = False
    elastic_http_compress: bool = True
    elastic_bulk_api_timeout: str = "30m"
    elastic_bulk_request_timeout_seconds: int = 1800
    elastic_bulk_batch_size: int = 100
    elastic_bulk_max_retries: int = 5
    docling_picture_description_url: str = (
        "http://vllm-qwen35-9b:8007/v1/chat/completions"
    )


_SERVER_CONFIG: ServerConfig | None = None


def _env_int(name: str, default: int) -> int:
    value = getenv(name)
    if value is None:
        return default
    return int(value)


def _env_bool(name: str, default: bool) -> bool:
    value = getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in _FALSE_VALUES


def _env_optional_string(name: str, default: str | None) -> str | None:
    value = getenv(name)
    if value is None:
        return default
    stripped = value.strip()
    return stripped or None


def _env_list(name: str, default: list[str]) -> list[str]:
    value = getenv(name)
    if value is None:
        return list(default)
    values = [item.strip() for item in value.split(",") if item.strip()]
    return values or list(default)


def _load_server_config_from_env() -> ServerConfig:
    physical_cuda_device = getenv("PHYSICAL_CUDA_DEVICE", "4")
    logical_cuda_device_index = _env_int("LOGICAL_CUDA_DEVICE_INDEX", 0)
    visible_cuda_devices = getenv(
        "CUDA_VISIBLE_DEVICES",
        str(logical_cuda_device_index),
    )
    docling_device = getenv("DOCLING_DEVICE", f"cuda:{logical_cuda_device_index}")
    elastic_url = getenv("ELASTIC_URL")
    elastic_hosts_default = [elastic_url] if elastic_url else _DEFAULT_ELASTIC_HOSTS

    return ServerConfig(
        app_name=getenv("APP_NAME", "ingest-server-orquestator"),
        environment=getenv("APP_ENV", "local"),
        inbound_queue_name=getenv("INBOUND_QUEUE_NAME", "inbound"),
        chunk_max_tokens=_env_int("CHUNK_MAX_TOKENS", 2048),
        tokenizer_path=Path(
            getenv(
                "TOKENIZER_PATH",
                "/datastore/models/tokenizers/qwen3-embedding-4b/",
            )
        ),
        cuda_device_order=getenv("CUDA_DEVICE_ORDER", "PCI_BUS_ID"),
        physical_cuda_device=physical_cuda_device,
        visible_cuda_devices=visible_cuda_devices,
        logical_cuda_device_index=logical_cuda_device_index,
        docling_device=docling_device,
        elastic_hosts=_env_list("ELASTIC_HOSTS", elastic_hosts_default),
        elastic_api_key=_env_optional_string(
            "ELASTIC_API_KEY",
            _DEFAULT_ELASTIC_API_KEY,
        ),
        elastic_index_name=getenv("ELASTIC_INDEX_NAME", "open-rag-embeddings-v3"),
        elastic_pipeline_name=getenv(
            "ELASTIC_PIPELINE_NAME",
            "open_rag_embeddings_v3_multilingual_semantic_pipeline",
        ),
        elastic_inference_id=getenv(
            "ELASTIC_INFERENCE_ID",
            _DEFAULT_ELASTIC_INFERENCE_ID,
        ),
        elastic_verify_certs=_env_bool("ELASTIC_VERIFY_CERTS", False),
        elastic_ssl_show_warn=_env_bool("ELASTIC_SSL_SHOW_WARN", False),
        docling_picture_description_url=getenv(
            "DOCLING_PICTURE_DESCRIPTION_URL",
            "http://vllm-qwen35-9b:8007/v1/chat/completions",
        ),
    )


def load_server_config() -> ServerConfig:
    global _SERVER_CONFIG

    if _SERVER_CONFIG is None:
        _SERVER_CONFIG = _load_server_config_from_env()
        LocalQueue()

    return _SERVER_CONFIG


def get_server_config() -> ServerConfig:
    return load_server_config()
