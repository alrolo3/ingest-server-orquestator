from __future__ import annotations

import logging
import time
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from pydantic import Field, PrivateAttr

from config.config import ServerConfig, get_server_config
from dispatcher.base_dispatcher import AbstractDispatcher
from model.document_chunk import DocumentChunk

if TYPE_CHECKING:
    from elasticsearch import Elasticsearch


LANGUAGE_DETECTION_MODEL = "lang_ident_model_1"
DEFAULT_LEXICAL_LANGUAGE = "en"
SPARSE_SEMANTIC_INFERENCE_ID = "bge-m3-sparse"
SPARSE_SEMANTIC_TASK_TYPE = "sparse_embedding"
RETRYABLE_BULK_ITEM_STATUSES = {429, 500, 502, 503, 504}
MAX_BULK_ITEM_RETRY_DELAY_SECONDS = 30
LOGGER = logging.getLogger(__name__)

MODEL_SETTINGS = {
    "service": "custom",
    "task_type": "text_embedding",
    "dimensions": 2560,
    "similarity": "dot_product",
    "element_type": "float",
}

SEMANTIC_TEXT_FIELD = {
    "type": "semantic_text",
    "model_settings": MODEL_SETTINGS,
    "index_options": {
        "dense_vector": {
            "element_type": "float",
            "type": "int8_hnsw",
            "m": 16,
            "ef_construction": 100,
        }
    },
    "chunking_settings": {
        "strategy": "none",
    },
}

SPARSE_SEMANTIC_TEXT_FIELD = {
    "type": "semantic_text",
    "inference_id": SPARSE_SEMANTIC_INFERENCE_ID,
    "chunking_settings": {
        "strategy": "none",
    },
}

CONTENT_LEX_PROPERTIES = {
    "es": {"type": "text", "analyzer": "spanish"},
    "en": {"type": "text", "analyzer": "english"},
    "fr": {"type": "text", "analyzer": "french"},
}

TITLE_FIELD = {
    "type": "text",
    "fields": {
        "keyword": {
            "type": "keyword",
            "ignore_above": 512,
        }
    },
}

OPEN_RAG_MAPPINGS = {
    "dynamic": False,
    "_source": {
        "excludes": [
            "content_lex.*",
            "language_detection",
        ]
    },
    "_meta": {
        "description": (
            "Multilingual RAG mapping adapted to DocumentChunk. The canonical "
            "chunk text is stored in dense content and sparse content_sparse "
            "semantic_text fields. Cleaned titles and Docling headings are "
            "indexed as sparse semantic_text. Lexical BM25 fields are generated "
            "by the ingest pipeline and excluded from _source."
        ),
        "language_detection_model": LANGUAGE_DETECTION_MODEL,
        "expected_model_settings": MODEL_SETTINGS,
        "sparse_semantic_inference": {
            "inference_id": SPARSE_SEMANTIC_INFERENCE_ID,
            "task_type": SPARSE_SEMANTIC_TASK_TYPE,
        },
        "chunking": (
            "Automatic semantic_text chunking is disabled because the service "
            "already indexes pre-chunked DocumentChunk records."
        ),
        "lexical_routing": (
            "The ingest pipeline detects language and copies content into exactly "
            "one content_lex.<lang> field for language-specific BM25 analysis."
        ),
        "default_lexical_language": DEFAULT_LEXICAL_LANGUAGE,
        "document_chunk_fields": [
            "content",
            "content_sparse",
            "document_id",
            "chunk_id",
            "chunk_index",
            "chunking_strategy",
            "content_token_count",
            "doc_items",
            "page_number",
            "page_numbers",
            "total_pages",
            "title",
            "clean_title",
            "headings",
            "source_file_name",
        ],
        "supported_lexical_languages": [
            "es",
            "en",
            "fr",
        ],
    },
    "properties": {
        "content": SEMANTIC_TEXT_FIELD,
        "content_sparse": SPARSE_SEMANTIC_TEXT_FIELD,
        "content_lex": {
            "properties": CONTENT_LEX_PROPERTIES,
        },
        "language": {"type": "keyword"},
        "language_probability": {"type": "float"},
        "clean_title": SPARSE_SEMANTIC_TEXT_FIELD,
        "headings": SPARSE_SEMANTIC_TEXT_FIELD,
        "title": TITLE_FIELD,
        "source_file_name": {
            "type": "keyword",
            "fields": {
                "text": {"type": "text"},
            },
        },
        "record_type": {"type": "keyword"},
        "document_id": {"type": "keyword"},
        "chunk_id": {"type": "keyword"},
        "chunk_index": {"type": "integer"},
        "chunking_strategy": {"type": "keyword"},
        "content_token_count": {"type": "integer"},
        "doc_items": {"type": "keyword"},
        "page_number": {"type": "integer"},
        "page_numbers": {"type": "integer"},
        "total_pages": {"type": "integer"},
        "searchable": {"type": "boolean"},
        "boilerplate": {"type": "boolean"},
        "content_kind": {"type": "keyword"},
        "content_length": {"type": "integer"},
        "ingest_error": {"type": "text"},
        "ingested_at": {"type": "date"},
    },
}

OPEN_RAG_PIPELINE = {
    "description": (
        "Escape inference-template placeholders, detect chunk language, route "
        "canonical content into one language-specific lexical field, and normalize "
        "DocumentChunk metadata."
    ),
    "processors": [
        {
            "set": {
                "field": "ingested_at",
                "value": "{{{_ingest.timestamp}}}",
                "override": False,
            }
        },
        {
            "script": {
                "description": (
                    "Escape Elasticsearch custom inference template placeholders "
                    "in semantic source text."
                ),
                "lang": "painless",
                "source": (
                    "String escapeText(def raw) { "
                    "if (raw == null) { return null; } "
                    "return raw.toString().replace('${', '$ {'); "
                    "} "
                    "if (ctx.content != null) { "
                    "ctx.content = escapeText(ctx.content); "
                    "} "
                    "if (ctx.content_sparse != null) { "
                    "ctx.content_sparse = escapeText(ctx.content_sparse); "
                    "} "
                    "if (ctx.clean_title != null) { "
                    "ctx.clean_title = escapeText(ctx.clean_title); "
                    "} "
                    "if (ctx.headings != null) { "
                    "def escapedHeadings = new ArrayList(); "
                    "if (ctx.headings instanceof List) { "
                    "for (def heading : ctx.headings) { "
                    "String escapedHeading = escapeText(heading); "
                    "if (escapedHeading != null && escapedHeading.length() > 0) { "
                    "escapedHeadings.add(escapedHeading); "
                    "} "
                    "} "
                    "} else { "
                    "String escapedHeading = escapeText(ctx.headings); "
                    "if (escapedHeading != null && escapedHeading.length() > 0) { "
                    "escapedHeadings.add(escapedHeading); "
                    "} "
                    "} "
                    "ctx.headings = escapedHeadings; "
                    "}"
                ),
            }
        },
        {
            "script": {
                "description": (
                    "Normalize DocumentChunk fields into indexed RAG helper fields."
                ),
                "lang": "painless",
                "source": (
                    "boolean isHex(String value) { "
                    "for (int i = 0; i < value.length(); i++) { "
                    "String c = value.substring(i, i + 1); "
                    "if (!\"0123456789abcdefABCDEF\".contains(c)) { return false; } "
                    "} "
                    "return true; "
                    "} "
                    "String stripExtension(String value) { "
                    "String lower = value.toLowerCase(); "
                    "if (lower.endsWith('.pdf')) { "
                    "return value.substring(0, value.length() - 4).trim(); "
                    "} "
                    "if (lower.endsWith('.docx') || lower.endsWith('.pptx') || "
                    "lower.endsWith('.xlsx') || lower.endsWith('.html')) { "
                    "return value.substring(0, value.length() - 5).trim(); "
                    "} "
                    "if (lower.endsWith('.doc') || lower.endsWith('.ppt') || "
                    "lower.endsWith('.xls') || lower.endsWith('.txt') || "
                    "lower.endsWith('.htm')) { "
                    "return value.substring(0, value.length() - 4).trim(); "
                    "} "
                    "if (lower.endsWith('.md')) { "
                    "return value.substring(0, value.length() - 3).trim(); "
                    "} "
                    "return value; "
                    "} "
                    "String sanitizeTitle(String value) { "
                    "StringBuilder cleaned = new StringBuilder(); "
                    "boolean previousSpace = true; "
                    "for (int i = 0; i < value.length();) { "
                    "int codePoint = value.codePointAt(i); "
                    "if (Character.isLetterOrDigit(codePoint)) { "
                    "cleaned.appendCodePoint(codePoint); "
                    "previousSpace = false; "
                    "} else if (!previousSpace) { "
                    "cleaned.append(' '); "
                    "previousSpace = true; "
                    "} "
                    "i += Character.charCount(codePoint); "
                    "} "
                    "return cleaned.toString().trim(); "
                    "} "
                    "String cleanTitle(def raw) { "
                    "if (raw == null) { return null; } "
                    "String value = raw.toString().trim(); "
                    "if (value.length() == 0) { return null; } "
                    "int forwardSlash = value.lastIndexOf(\"/\"); "
                    "int backSlash = value.lastIndexOf(\"\\\\\"); "
                    "int slash = forwardSlash > backSlash ? forwardSlash : backSlash; "
                    "if (slash >= 0 && slash + 1 < value.length()) { "
                    "value = value.substring(slash + 1).trim(); "
                    "} "
                    "if (value.length() > 33 && value.substring(32, 33) == \"-\" && "
                    "isHex(value.substring(0, 32))) { "
                    "value = value.substring(33).trim(); "
                    "} else if (value.length() > 37 && value.substring(8, 9) == \"-\" && "
                    "value.substring(13, 14) == \"-\" && value.substring(18, 19) == \"-\" && "
                    "value.substring(23, 24) == \"-\" && value.substring(36, 37) == \"-\") { "
                    "String compact = value.substring(0, 8) + value.substring(9, 13) + "
                    "value.substring(14, 18) + value.substring(19, 23) + "
                    "value.substring(24, 36); "
                    "if (isHex(compact)) { value = value.substring(37).trim(); } "
                    "} "
                    "value = stripExtension(value); "
                    "value = sanitizeTitle(value); "
                    "return value.length() == 0 ? null : value; "
                    "} "
                    "List normalizeTextList(def raw) { "
                    "def values = new ArrayList(); "
                    "def seen = new HashSet(); "
                    "if (raw == null) { return values; } "
                    "if (raw instanceof List) { "
                    "for (def item : raw) { "
                    "if (item == null) { continue; } "
                    "String value = item.toString().trim(); "
                    "if (value.length() == 0 || seen.contains(value)) { continue; } "
                    "seen.add(value); "
                    "values.add(value); "
                    "} "
                    "} else { "
                    "String value = raw.toString().trim(); "
                    "if (value.length() > 0) { values.add(value); } "
                    "} "
                    "return values; "
                    "} "
                    "if (ctx.record_type == null) { ctx.record_type = 'chunk'; } "
                    "String title = cleanTitle(ctx.title); "
                    "String cleanedTitle = cleanTitle(ctx.clean_title); "
                    "String sourceTitle = cleanTitle(ctx.source_file_name); "
                    "if (title != null) { ctx.title = title; } "
                    "if (cleanedTitle == null) { cleanedTitle = title; } "
                    "if (cleanedTitle == null) { cleanedTitle = sourceTitle; } "
                    "if (cleanedTitle != null) { ctx.clean_title = cleanedTitle; } "
                    "if (ctx.title == null && cleanedTitle != null) { "
                    "ctx.title = cleanedTitle; "
                    "} "
                    "ctx.headings = normalizeTextList(ctx.headings); "
                    "if (ctx.content != null) { "
                    "ctx.content_length = ctx.content.length(); "
                    "if (ctx.content_sparse == null) { ctx.content_sparse = ctx.content; } "
                    "} "
                    "if (ctx.searchable == null) { ctx.searchable = true; } "
                    "if (ctx.boilerplate == null) { ctx.boilerplate = false; } "
                    "if (ctx.content_kind == null) { ctx.content_kind = 'chunk'; }"
                ),
            }
        },
        {
            "inference": {
                "if": "ctx.content != null && ctx.content.length() > 0",
                "model_id": LANGUAGE_DETECTION_MODEL,
                "field_map": {
                    "content": "text",
                },
                "inference_config": {
                    "classification": {
                        "num_top_classes": 3,
                    }
                },
                "target_field": "language_detection",
            }
        },
        {
            "script": {
                "description": (
                    "Choose a supported lexical analyzer field and copy content "
                    "into exactly one content_lex.<language> field."
                ),
                "lang": "painless",
                "source": (
                    "def supported = ['es', 'en', 'fr']; "
                    "def lang = null; "
                    "double prob = 0.0; "
                    "if (ctx.language_detection != null) { "
                    "if (ctx.language_detection.predicted_value != null) { "
                    "lang = ctx.language_detection.predicted_value; "
                    "} "
                    "if (ctx.language_detection.top_classes != null && "
                    "ctx.language_detection.top_classes.size() > 0 && "
                    "ctx.language_detection.top_classes[0].class_probability "
                    "!= null) { "
                    "prob = ctx.language_detection.top_classes[0].class_probability; "
                    "} "
                    "} "
                    "if (lang == null || lang == 'zxx' || prob < 0.60 || "
                    "!supported.contains(lang)) { lang = '"
                    f"{DEFAULT_LEXICAL_LANGUAGE}"
                    "'; } "
                    "ctx.language = lang; "
                    "ctx.language_probability = prob; "
                    "if (ctx.content != null) { "
                    "if (ctx.content_lex == null) { ctx.content_lex = new HashMap(); } "
                    "ctx.content_lex[lang] = ctx.content; "
                    "}"
                ),
            }
        },
        {
            "remove": {
                "field": [
                    "content_semantic",
                    "language_detection",
                    "chunker_strategy",
                    "raw_data",
                    "raw_text",
                    "title_semantic",
                    "title_sparse",
                ],
                "ignore_missing": True,
            }
        },
    ],
    "on_failure": [
        {
            "set": {
                "field": "ingest_error",
                "value": "{{{ _ingest.on_failure_message }}}",
            }
        }
    ],
}


def build_open_rag_mappings(inference_id: str) -> dict[str, Any]:
    mappings = deepcopy(OPEN_RAG_MAPPINGS)
    mappings["_meta"]["inference_id"] = inference_id
    mappings["_meta"]["sparse_semantic_inference"] = {
        "inference_id": SPARSE_SEMANTIC_INFERENCE_ID,
        "task_type": SPARSE_SEMANTIC_TASK_TYPE,
    }
    mappings["properties"]["content"] = deepcopy(SEMANTIC_TEXT_FIELD)
    for field_name in ("content_sparse", "clean_title", "headings"):
        mappings["properties"][field_name] = deepcopy(SPARSE_SEMANTIC_TEXT_FIELD)
    mappings["properties"]["content"]["inference_id"] = inference_id
    return mappings


class ElasticsearchDispatch(AbstractDispatcher):
    """Dispatcher skeleton backed by the Elasticsearch Python client."""

    hosts: list[str] = Field(default_factory=list)
    api_key: str | None = None
    index_name: str
    pipeline_name: str
    inference_id: str
    verify_certs: bool
    ssl_show_warn: bool
    http_compress: bool
    bulk_api_timeout: str
    bulk_request_timeout_seconds: int
    bulk_batch_size: int
    bulk_max_retries: int

    _client: Elasticsearch = PrivateAttr()

    def __init__(
        self,
        server_config: ServerConfig | None = None,
        **data: object,
    ) -> None:
        config = server_config or get_server_config()
        config_data: dict[str, object] = {
            "hosts": config.elastic_hosts,
            "api_key": config.elastic_api_key,
            "index_name": config.elastic_index_name,
            "pipeline_name": config.elastic_pipeline_name,
            "inference_id": config.elastic_inference_id,
            "verify_certs": config.elastic_verify_certs,
            "ssl_show_warn": config.elastic_ssl_show_warn,
            "http_compress": config.elastic_http_compress,
            "bulk_api_timeout": config.elastic_bulk_api_timeout,
            "bulk_request_timeout_seconds": config.elastic_bulk_request_timeout_seconds,
            "bulk_batch_size": config.elastic_bulk_batch_size,
            "bulk_max_retries": config.elastic_bulk_max_retries,
        }
        config_data.update(data)
        super().__init__(**config_data)
        self._client = self._build_client()
        self._ensure_pipeline()
        self._ensure_index()

    def _build_client(self) -> Elasticsearch:
        from elasticsearch import Elasticsearch

        client_options = {
            "hosts": self.hosts,
            "verify_certs": self.verify_certs,
            "ssl_show_warn": self.ssl_show_warn,
            "http_compress": self.http_compress,
        }
        if self.api_key is None:
            return Elasticsearch(**client_options)
        return Elasticsearch(**client_options, api_key=self.api_key)

    def _ensure_pipeline(self) -> None:
        pipeline = deepcopy(OPEN_RAG_PIPELINE)
        self._client.ingest.put_pipeline(
            id=self.pipeline_name,
            description=pipeline["description"],
            processors=pipeline["processors"],
            on_failure=pipeline["on_failure"],
        )

    def _ensure_index(self) -> None:
        if bool(self._client.indices.exists(index=self.index_name)):
            return

        self._client.indices.create(
            index=self.index_name,
            settings={
                "index.default_pipeline": self.pipeline_name,
            },
            mappings=build_open_rag_mappings(self.inference_id),
        )

    def dispatch_chunks(self, chunks: list[DocumentChunk]) -> None:
        if not chunks:
            return

        for start in range(0, len(chunks), self.bulk_batch_size):
            batch = chunks[start : start + self.bulk_batch_size]
            retry_batch = batch
            retry_count = 0

            while retry_batch:
                operations = self._bulk_operations(retry_batch)
                response = self._client.options(
                    request_timeout=self.bulk_request_timeout_seconds,
                    max_retries=self.bulk_max_retries,
                    retry_on_timeout=True,
                    retry_on_status=(429, 500, 502, 503, 504),
                ).bulk(
                    operations=operations,
                    pipeline=self.pipeline_name,
                    refresh="wait_for",
                    timeout=self.bulk_api_timeout,
                    wait_for_active_shards="1",
                )

                response_body = getattr(response, "body", response)
                failed_items = self._failed_bulk_items(response_body)
                if not failed_items:
                    break

                retry_ids = self._retryable_failed_item_ids(failed_items)
                if (
                    len(retry_ids) != len(failed_items)
                    or retry_count >= self.bulk_max_retries
                ):
                    raise RuntimeError(
                        "Elasticsearch bulk chunk dispatch failed for "
                        f"{len(failed_items)} item(s): {failed_items[:3]}"
                    )

                retry_count += 1
                LOGGER.warning(
                    "Retrying %s transient Elasticsearch bulk item failure(s) "
                    "attempt=%s/%s",
                    len(retry_ids),
                    retry_count,
                    self.bulk_max_retries,
                )
                time.sleep(self._bulk_item_retry_delay_seconds(retry_count))
                next_retry_batch = [
                    chunk for chunk in retry_batch if chunk.chunk_id in retry_ids
                ]
                if len(next_retry_batch) != len(retry_ids):
                    raise RuntimeError(
                        "Elasticsearch bulk chunk dispatch failed for "
                        f"{len(failed_items)} item(s): {failed_items[:3]}"
                    )
                retry_batch = next_retry_batch

    def _bulk_operations(self, chunks: list[DocumentChunk]) -> list[dict[str, Any]]:
        operations = []
        for chunk in chunks:
            operations.append(
                {
                    "index": {
                        "_index": self.index_name,
                        "_id": chunk.chunk_id,
                    }
                }
            )
            operations.append(chunk.model_dump(exclude_none=True))
        return operations

    @staticmethod
    def _failed_bulk_items(response_body: dict[str, Any]) -> list[dict[str, Any]]:
        if not response_body.get("errors", False):
            return []
        return [
            operation
            for item in response_body.get("items", [])
            for operation in item.values()
            if operation.get("error") is not None
        ]

    @staticmethod
    def _retryable_failed_item_ids(failed_items: list[dict[str, Any]]) -> set[str]:
        retry_ids = set()
        for item in failed_items:
            status = item.get("status")
            item_id = item.get("_id")
            if status in RETRYABLE_BULK_ITEM_STATUSES and isinstance(item_id, str):
                retry_ids.add(item_id)
        return retry_ids

    @staticmethod
    def _bulk_item_retry_delay_seconds(retry_count: int) -> int:
        return min(2 ** (retry_count - 1), MAX_BULK_ITEM_RETRY_DELAY_SECONDS)

    def dispatch_markdown(self, markdown: str) -> None:
        raise NotImplementedError
