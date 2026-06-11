from __future__ import annotations

from dataclasses import dataclass, field
from os import getenv
from pathlib import Path

from config.paths import (
    DOCLING_ARTIFACTS_PATH,
    DOCLING_MINERU_MODEL_PATH,
    DOCLING_PP_LAYOUT_MODEL_PATH,
    TOKENIZER_PATH,
)
from queues.queue_local import LocalQueue


_DEFAULT_ELASTIC_HOSTS = ["https://localhost:9200"]
_DEFAULT_ELASTIC_API_KEY = (
    "RW9RbG1aNEJ4QVZwbFVaNjNhOEc6QTY1b1V2cDU4MUUxWHZjeTkxTkx4UQ=="
)
_DEFAULT_ELASTIC_INFERENCE_ID = "qwen3-embedding-4b"
_APP_NAME = "ingest-server-orquestator"
_INBOUND_QUEUE_NAME = "inbound"
_WORKER_MAX_WORKERS = 1
_CHUNK_MAX_TOKENS = 8192
_CUDA_DEVICE_ORDER = "PCI_BUS_ID"
_VISIBLE_CUDA_DEVICES = "0"
_LOGICAL_CUDA_DEVICE_INDEX = 0
_DOCLING_DEVICE = "cuda:0"
_DOCLING_OCR_ENABLED = True
_DOCLING_OCR_ENGINE = "easyocr"
_DOCLING_EASY_OCR_LANGS = ["es", "en"]
_DOCLING_MINERU_DEVICE = "auto"
_DOCLING_MINERU_DTYPE = "auto"
_DOCLING_MINERU_BATCH_SIZE = 1
_DOCLING_MINERU_IMAGE_ANALYSIS = False
_DOCLING_SURYA_SCALE = 2.0
_DOCLING_SURYA_CONFIDENCE = 1.0
_DOCLING_SURYA_INFERENCE_URL: str | None = None
_DOCLING_SURYA_INFERENCE_BACKEND: str | None = None
_DOCLING_SURYA_INFERENCE_PARALLEL = 8
_DOCLING_SURYA_KEEP_ALIVE = True
_DOCLING_RAPID_OCR_LANGS = ["english"]
_DOCLING_AUTO_OCR_LANGS: list[str] = []
_DOCLING_FORCE_FULL_PAGE_OCR = False
_DOCLING_OCR_BITMAP_AREA_THRESHOLD = 0.05
_DOCLING_OCR_BATCH_SIZE = 8
_DOCLING_LAYOUT_BATCH_SIZE = 4
_DOCLING_TABLE_BATCH_SIZE = 8
_DOCLING_QUEUE_MAX_SIZE = 16
_DOCLING_ACCELERATOR_THREADS = 8
_DOCLING_PICTURE_DESCRIPTION_ENABLED = True
_DOCLING_PICTURE_CLASSIFICATION_ENABLED = True
_DOCLING_PICTURE_DESCRIPTION_CONCURRENCY = 16
_DOCLING_PICTURE_DESCRIPTION_TIMEOUT = 240
_DOCLING_IMAGES_SCALE = 2.0
_DOCLING_TABLE_MODE = "accurate"
_DOCLING_CODE_ENRICHMENT_ENABLED = False
_DOCLING_FORMULA_ENRICHMENT_ENABLED = False
_FALSE_VALUES = {"", "0", "false", "no", "off"}
_DOCLING_TABLE_MODES = {"accurate", "fast"}


def _default_elastic_hosts() -> list[str]:
    return list(_DEFAULT_ELASTIC_HOSTS)


def _default_docling_ocr_langs() -> list[str]:
    return list(_DOCLING_EASY_OCR_LANGS)


@dataclass(frozen=True, slots=True)
class ServerConfig:
    app_name: str
    environment: str
    inbound_queue_name: str
    chunk_max_tokens: int
    tokenizer_path: Path
    docling_artifacts_path: Path
    docling_pp_layout_model_path: Path
    docling_mineru_model_path: Path = DOCLING_MINERU_MODEL_PATH
    worker_max_workers: int = _WORKER_MAX_WORKERS
    cuda_device_order: str = _CUDA_DEVICE_ORDER
    visible_cuda_devices: str = _VISIBLE_CUDA_DEVICES
    logical_cuda_device_index: int = _LOGICAL_CUDA_DEVICE_INDEX
    docling_device: str = _DOCLING_DEVICE
    docling_ocr_enabled: bool = _DOCLING_OCR_ENABLED
    docling_ocr_engine: str = _DOCLING_OCR_ENGINE
    docling_ocr_langs: list[str] = field(default_factory=_default_docling_ocr_langs)
    docling_mineru_device: str = _DOCLING_MINERU_DEVICE
    docling_mineru_dtype: str = _DOCLING_MINERU_DTYPE
    docling_mineru_batch_size: int = _DOCLING_MINERU_BATCH_SIZE
    docling_mineru_image_analysis: bool = _DOCLING_MINERU_IMAGE_ANALYSIS
    docling_surya_scale: float = _DOCLING_SURYA_SCALE
    docling_surya_confidence: float = _DOCLING_SURYA_CONFIDENCE
    docling_surya_inference_url: str | None = _DOCLING_SURYA_INFERENCE_URL
    docling_surya_inference_backend: str | None = _DOCLING_SURYA_INFERENCE_BACKEND
    docling_surya_inference_parallel: int = _DOCLING_SURYA_INFERENCE_PARALLEL
    docling_surya_keep_alive: bool = _DOCLING_SURYA_KEEP_ALIVE
    docling_force_full_page_ocr: bool = _DOCLING_FORCE_FULL_PAGE_OCR
    docling_ocr_bitmap_area_threshold: float = _DOCLING_OCR_BITMAP_AREA_THRESHOLD
    docling_ocr_batch_size: int = _DOCLING_OCR_BATCH_SIZE
    docling_layout_batch_size: int = _DOCLING_LAYOUT_BATCH_SIZE
    docling_table_batch_size: int = _DOCLING_TABLE_BATCH_SIZE
    docling_queue_max_size: int = _DOCLING_QUEUE_MAX_SIZE
    docling_accelerator_threads: int = _DOCLING_ACCELERATOR_THREADS
    docling_picture_description_enabled: bool = _DOCLING_PICTURE_DESCRIPTION_ENABLED
    docling_picture_classification_enabled: bool = _DOCLING_PICTURE_CLASSIFICATION_ENABLED
    docling_picture_description_concurrency: int = (
        _DOCLING_PICTURE_DESCRIPTION_CONCURRENCY
    )
    docling_picture_description_timeout: int = _DOCLING_PICTURE_DESCRIPTION_TIMEOUT
    docling_images_scale: float = _DOCLING_IMAGES_SCALE
    docling_table_mode: str = _DOCLING_TABLE_MODE
    docling_code_enrichment_enabled: bool = _DOCLING_CODE_ENRICHMENT_ENABLED
    docling_formula_enrichment_enabled: bool = _DOCLING_FORMULA_ENRICHMENT_ENABLED
    elastic_hosts: list[str] = field(default_factory=_default_elastic_hosts)
    elastic_api_key: str | None = _DEFAULT_ELASTIC_API_KEY
    elastic_index_name: str = "open-rag-embeddings-v4"
    elastic_pipeline_name: str = "open_rag_embeddings_v4_multilingual_semantic_pipeline"
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


def _env_bool(name: str, default: bool) -> bool:
    value = getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in _FALSE_VALUES


def _env_int(name: str, default: int) -> int:
    value = getenv(name)
    if value is None:
        return default
    stripped = value.strip()
    return int(stripped) if stripped else default


def _env_float(name: str, default: float) -> float:
    value = getenv(name)
    if value is None:
        return default
    stripped = value.strip()
    return float(stripped) if stripped else default


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


def _env_choice(name: str, default: str, choices: set[str]) -> str:
    value = getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    if normalized not in choices:
        valid = ", ".join(sorted(choices))
        raise ValueError(f"{name} must be one of: {valid}")
    return normalized


def _docling_ocr_engine() -> str:
    return getenv("DOCLING_OCR_ENGINE", _DOCLING_OCR_ENGINE).strip().lower()


def _default_ocr_langs_for_engine(engine: str) -> list[str]:
    if engine == "rapidocr":
        return list(_DOCLING_RAPID_OCR_LANGS)
    if engine == "auto":
        return list(_DOCLING_AUTO_OCR_LANGS)
    return list(_DOCLING_EASY_OCR_LANGS)


def _load_server_config_from_env() -> ServerConfig:
    elastic_url = getenv("ELASTIC_URL")
    elastic_hosts_default = [elastic_url] if elastic_url else _DEFAULT_ELASTIC_HOSTS
    docling_ocr_engine = _docling_ocr_engine()

    return ServerConfig(
        app_name=_APP_NAME,
        environment=getenv("APP_ENV", "local"),
        inbound_queue_name=_INBOUND_QUEUE_NAME,
        worker_max_workers=max(
            1,
            _env_int("INGEST_WORKER_MAX_WORKERS", _WORKER_MAX_WORKERS),
        ),
        chunk_max_tokens=_CHUNK_MAX_TOKENS,
        tokenizer_path=TOKENIZER_PATH,
        docling_artifacts_path=DOCLING_ARTIFACTS_PATH,
        docling_pp_layout_model_path=DOCLING_PP_LAYOUT_MODEL_PATH,
        docling_mineru_model_path=DOCLING_MINERU_MODEL_PATH,
        cuda_device_order=_CUDA_DEVICE_ORDER,
        visible_cuda_devices=_VISIBLE_CUDA_DEVICES,
        logical_cuda_device_index=_LOGICAL_CUDA_DEVICE_INDEX,
        docling_device=_DOCLING_DEVICE,
        docling_ocr_enabled=_env_bool("DOCLING_OCR_ENABLED", _DOCLING_OCR_ENABLED),
        docling_ocr_engine=docling_ocr_engine,
        docling_ocr_langs=_env_list(
            "DOCLING_OCR_LANGS",
            _default_ocr_langs_for_engine(docling_ocr_engine),
        ),
        docling_mineru_device=getenv(
            "DOCLING_MINERU_DEVICE",
            _DOCLING_MINERU_DEVICE,
        ).strip()
        or _DOCLING_MINERU_DEVICE,
        docling_mineru_dtype=getenv(
            "DOCLING_MINERU_DTYPE",
            _DOCLING_MINERU_DTYPE,
        ).strip()
        or _DOCLING_MINERU_DTYPE,
        docling_mineru_batch_size=max(
            1,
            _env_int("DOCLING_MINERU_BATCH_SIZE", _DOCLING_MINERU_BATCH_SIZE),
        ),
        docling_mineru_image_analysis=_env_bool(
            "DOCLING_MINERU_IMAGE_ANALYSIS",
            _DOCLING_MINERU_IMAGE_ANALYSIS,
        ),
        docling_surya_scale=_env_float(
            "DOCLING_SURYA_SCALE",
            _DOCLING_SURYA_SCALE,
        ),
        docling_surya_confidence=_env_float(
            "DOCLING_SURYA_CONFIDENCE",
            _DOCLING_SURYA_CONFIDENCE,
        ),
        docling_surya_inference_url=_env_optional_string(
            "DOCLING_SURYA_INFERENCE_URL",
            _DOCLING_SURYA_INFERENCE_URL,
        ),
        docling_surya_inference_backend=_env_optional_string(
            "DOCLING_SURYA_INFERENCE_BACKEND",
            _DOCLING_SURYA_INFERENCE_BACKEND,
        ),
        docling_surya_inference_parallel=max(
            1,
            _env_int(
                "DOCLING_SURYA_INFERENCE_PARALLEL",
                _DOCLING_SURYA_INFERENCE_PARALLEL,
            ),
        ),
        docling_surya_keep_alive=_env_bool(
            "DOCLING_SURYA_KEEP_ALIVE",
            _DOCLING_SURYA_KEEP_ALIVE,
        ),
        docling_force_full_page_ocr=_env_bool(
            "DOCLING_FORCE_FULL_PAGE_OCR",
            _DOCLING_FORCE_FULL_PAGE_OCR,
        ),
        docling_ocr_bitmap_area_threshold=_env_float(
            "DOCLING_OCR_BITMAP_AREA_THRESHOLD",
            _DOCLING_OCR_BITMAP_AREA_THRESHOLD,
        ),
        docling_ocr_batch_size=max(
            1,
            _env_int("DOCLING_OCR_BATCH_SIZE", _DOCLING_OCR_BATCH_SIZE),
        ),
        docling_layout_batch_size=max(
            1,
            _env_int("DOCLING_LAYOUT_BATCH_SIZE", _DOCLING_LAYOUT_BATCH_SIZE),
        ),
        docling_table_batch_size=max(
            1,
            _env_int("DOCLING_TABLE_BATCH_SIZE", _DOCLING_TABLE_BATCH_SIZE),
        ),
        docling_queue_max_size=max(
            1,
            _env_int("DOCLING_QUEUE_MAX_SIZE", _DOCLING_QUEUE_MAX_SIZE),
        ),
        docling_accelerator_threads=max(
            1,
            _env_int("DOCLING_ACCELERATOR_THREADS", _DOCLING_ACCELERATOR_THREADS),
        ),
        docling_picture_description_enabled=_env_bool(
            "DOCLING_PICTURE_DESCRIPTION_ENABLED",
            _DOCLING_PICTURE_DESCRIPTION_ENABLED,
        ),
        docling_picture_classification_enabled=_env_bool(
            "DOCLING_PICTURE_CLASSIFICATION_ENABLED",
            _DOCLING_PICTURE_CLASSIFICATION_ENABLED,
        ),
        docling_picture_description_concurrency=max(
            1,
            _env_int(
                "DOCLING_PICTURE_DESCRIPTION_CONCURRENCY",
                _DOCLING_PICTURE_DESCRIPTION_CONCURRENCY,
            ),
        ),
        docling_picture_description_timeout=max(
            1,
            _env_int(
                "DOCLING_PICTURE_DESCRIPTION_TIMEOUT",
                _DOCLING_PICTURE_DESCRIPTION_TIMEOUT,
            ),
        ),
        docling_images_scale=max(
            0.1,
            _env_float("DOCLING_IMAGES_SCALE", _DOCLING_IMAGES_SCALE),
        ),
        docling_table_mode=_env_choice(
            "DOCLING_TABLE_MODE",
            _DOCLING_TABLE_MODE,
            _DOCLING_TABLE_MODES,
        ),
        docling_code_enrichment_enabled=_env_bool(
            "DOCLING_CODE_ENRICHMENT_ENABLED",
            _DOCLING_CODE_ENRICHMENT_ENABLED,
        ),
        docling_formula_enrichment_enabled=_env_bool(
            "DOCLING_FORMULA_ENRICHMENT_ENABLED",
            _DOCLING_FORMULA_ENRICHMENT_ENABLED,
        ),
        elastic_hosts=_env_list("ELASTIC_HOSTS", elastic_hosts_default),
        elastic_api_key=_env_optional_string(
            "ELASTIC_API_KEY",
            _DEFAULT_ELASTIC_API_KEY,
        ),
        elastic_index_name=getenv("ELASTIC_INDEX_NAME", "open-rag-embeddings-v4"),
        elastic_pipeline_name=getenv(
            "ELASTIC_PIPELINE_NAME",
            "open_rag_embeddings_v4_multilingual_semantic_pipeline",
        ),
        elastic_inference_id=getenv(
            "ELASTIC_INFERENCE_ID",
            _DEFAULT_ELASTIC_INFERENCE_ID,
        ),
        elastic_verify_certs=_env_bool("ELASTIC_VERIFY_CERTS", False),
        elastic_ssl_show_warn=_env_bool("ELASTIC_SSL_SHOW_WARN", False),
        elastic_http_compress=_env_bool("ELASTIC_HTTP_COMPRESS", True),
        elastic_bulk_api_timeout=getenv("ELASTIC_BULK_API_TIMEOUT", "30m"),
        elastic_bulk_request_timeout_seconds=_env_int(
            "ELASTIC_BULK_REQUEST_TIMEOUT_SECONDS",
            1800,
        ),
        elastic_bulk_batch_size=_env_int("ELASTIC_BULK_BATCH_SIZE", 100),
        elastic_bulk_max_retries=_env_int("ELASTIC_BULK_MAX_RETRIES", 5),
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
