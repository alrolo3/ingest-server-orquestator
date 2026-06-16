import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from dispatcher.elastic.elastic import (
    DENSE_SEMANTIC_INFERENCE_ID,
    ElasticsearchDispatch,
    OPEN_RAG_PIPELINE,
    RECOVERABLE_DOCUMENT_FIELD_MAPPINGS,
    build_open_rag_mappings,
)
from model.document_chunk import DocumentChunk


class FakeIndices:
    def __init__(self, exists: bool) -> None:
        self.exists_value = exists
        self.create_calls: list[dict[str, object]] = []
        self.put_mapping_calls: list[dict[str, object]] = []

    def exists(self, *, index: str) -> bool:
        return self.exists_value

    def create(self, **kwargs: object) -> None:
        self.create_calls.append(kwargs)

    def get_mapping(self, *, index: str) -> dict[str, object]:
        raise AssertionError("existing index mappings should not be inspected")

    def put_mapping(self, **kwargs: object) -> None:
        self.put_mapping_calls.append(kwargs)


class FakeClient:
    def __init__(self, index_exists: bool) -> None:
        self.indices = FakeIndices(index_exists)


class FakeBulkClient:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = responses
        self.bulk_chunk_ids: list[list[str]] = []
        self.options_calls: list[dict[str, object]] = []

    def options(self, **kwargs: object) -> "FakeBulkClient":
        self.options_calls.append(kwargs)
        return self

    def bulk(self, *, operations: list[dict[str, object]], **kwargs: object) -> object:
        self.bulk_chunk_ids.append(
            [
                operation["index"]["_id"]
                for operation in operations
                if "index" in operation
            ]
        )
        return self.responses.pop(0)


def _chunk(chunk_id: str, chunk_index: int = 0) -> DocumentChunk:
    return DocumentChunk(
        content="body",
        content_sparse="body",
        document_id="doc-1",
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        chunking_strategy="token",
        source_file_name="source.pdf",
    )


def _bulk_response(*items: dict[str, object]) -> dict[str, object]:
    return {
        "errors": any("error" in item for item in items),
        "items": [{"index": item} for item in items],
    }


def _dispatch_with_bulk_client(
    responses: list[dict[str, object]],
    *,
    bulk_max_retries: int = 2,
) -> tuple[ElasticsearchDispatch, FakeBulkClient]:
    dispatch = ElasticsearchDispatch.model_construct(
        index_name="rag-index",
        pipeline_name="rag-pipeline",
        bulk_api_timeout="1m",
        bulk_request_timeout_seconds=30,
        bulk_batch_size=10,
        bulk_max_retries=bulk_max_retries,
    )
    client = FakeBulkClient(responses)
    dispatch._client = client
    return dispatch, client


class ElasticsearchDispatchTest(unittest.TestCase):
    def test_pipeline_title_normalization_avoids_char_overloads(self) -> None:
        script_sources = [
            processor["script"]["source"]
            for processor in OPEN_RAG_PIPELINE["processors"]
            if "script" in processor
        ]
        normalization_source = next(
            source for source in script_sources if "String cleanTitle" in source
        )

        self.assertNotIn("char c =", normalization_source)
        self.assertNotIn("charAt(", normalization_source)
        self.assertNotIn("Math.max(", normalization_source)
        self.assertNotIn("replaceAll(", normalization_source)
        self.assertNotIn("lastIndexOf('/')", normalization_source)
        self.assertNotIn("lastIndexOf('\\\\')", normalization_source)
        self.assertIn('lastIndexOf("/")', normalization_source)
        self.assertIn('lastIndexOf("\\\\")', normalization_source)

    def test_ensure_index_creates_new_mapping_with_semantic_endpoints(self) -> None:
        dispatch = ElasticsearchDispatch.model_construct(
            index_name="rag-index",
            pipeline_name="rag-pipeline",
            inference_id=DENSE_SEMANTIC_INFERENCE_ID,
        )
        dispatch._client = FakeClient(index_exists=False)

        dispatch._ensure_index()

        calls = dispatch._client.indices.create_calls
        self.assertEqual(1, len(calls))
        self.assertEqual("rag-index", calls[0]["index"])
        self.assertEqual(
            {"index.default_pipeline": "rag-pipeline"},
            calls[0]["settings"],
        )
        mappings = calls[0]["mappings"]
        self.assertEqual(build_open_rag_mappings(DENSE_SEMANTIC_INFERENCE_ID), mappings)
        self.assertEqual(
            {"type": "text"},
            mappings["properties"]["content"],
        )
        self.assertEqual(
            DENSE_SEMANTIC_INFERENCE_ID,
            mappings["properties"]["content_dense"]["inference_id"],
        )
        self.assertEqual(
            "cosine",
            mappings["properties"]["content_dense"]["model_settings"]["similarity"],
        )
        self.assertEqual(
            {
                "element_type": "float",
                "type": "hnsw",
                "m": 32,
                "ef_construction": 200,
            },
            mappings["properties"]["content_dense"]["index_options"]["dense_vector"],
        )
        self.assertIn("content_dense", mappings["_source"]["excludes"])
        self.assertIn("content_sparse", mappings["_source"]["excludes"])
        self.assertNotIn("content_lex.*", mappings["_source"]["excludes"])
        self.assertNotIn("content", mappings["_source"]["excludes"])
        self.assertNotIn("clean_title", mappings["_source"]["excludes"])
        self.assertNotIn("headings", mappings["_source"]["excludes"])
        self.assertNotIn("content_lex", mappings["properties"])
        self.assertNotIn("language", mappings["properties"])
        self.assertNotIn("language_probability", mappings["properties"])
        for field_name in ("content_sparse", "clean_title", "headings"):
            self.assertEqual(
                "naver-splade-v3",
                mappings["properties"][field_name]["inference_id"],
            )

    def test_ensure_index_leaves_existing_index_unchanged(self) -> None:
        dispatch = ElasticsearchDispatch.model_construct(
            index_name="rag-index",
            pipeline_name="rag-pipeline",
            inference_id="custom-inference",
        )
        dispatch._client = FakeClient(index_exists=True)

        dispatch._ensure_index()

        self.assertEqual([], dispatch._client.indices.create_calls)
        self.assertEqual(
            [
                {
                    "index": "rag-index",
                    "properties": RECOVERABLE_DOCUMENT_FIELD_MAPPINGS,
                }
            ],
            dispatch._client.indices.put_mapping_calls,
        )

    def test_pipeline_populates_v4_sparse_fields_and_removes_old_fields(self) -> None:
        script_sources = [
            processor["script"]["source"]
            for processor in OPEN_RAG_PIPELINE["processors"]
            if "script" in processor
        ]
        escape_source = next(source for source in script_sources if "$ {" in source)
        normalization_source = next(
            source for source in script_sources if "String cleanTitle" in source
        )

        self.assertIn("ctx.content_dense = escapeText(ctx.content_dense)", escape_source)
        self.assertIn("ctx.content_sparse = escapeText(ctx.content_sparse)", escape_source)
        self.assertIn("ctx.clean_title = escapeText(ctx.clean_title)", escape_source)
        self.assertIn("for (def heading : ctx.headings)", escape_source)
        self.assertIn("String cleanedTitle = cleanTitle(ctx.clean_title)", normalization_source)
        self.assertIn("String sourceTitle = cleanTitle(ctx.source_file_name)", normalization_source)
        self.assertIn("ctx.headings = normalizeTextList(ctx.headings)", normalization_source)
        self.assertIn("ctx.content_dense = ctx.content", normalization_source)
        self.assertIn("ctx.content_sparse = ctx.content", normalization_source)

        remove_fields = [
            field
            for processor in OPEN_RAG_PIPELINE["processors"]
            if "remove" in processor
            for field in processor["remove"]["field"]
        ]
        self.assertIn("title_semantic", remove_fields)
        self.assertIn("title_sparse", remove_fields)
        self.assertIn("raw_text", remove_fields)
        self.assertIn("raw_data", remove_fields)
        self.assertNotIn("language_detection", remove_fields)
        self.assertNotIn("content_lex", "".join(script_sources))
        self.assertFalse(any("inference" in processor for processor in OPEN_RAG_PIPELINE["processors"]))

    def test_dispatch_chunks_retries_only_transient_failed_bulk_items(self) -> None:
        dispatch, client = _dispatch_with_bulk_client(
            [
                _bulk_response(
                    {"_id": "chunk-1", "status": 201},
                    {
                        "_id": "chunk-2",
                        "status": 500,
                        "error": {
                            "type": "inference_exception",
                            "reason": "node disconnected",
                        },
                    },
                ),
                _bulk_response({"_id": "chunk-2", "status": 201}),
            ]
        )

        with patch("dispatcher.elastic.elastic.time.sleep") as sleep:
            dispatch.dispatch_chunks([_chunk("chunk-1"), _chunk("chunk-2", 1)])

        self.assertEqual([["chunk-1", "chunk-2"], ["chunk-2"]], client.bulk_chunk_ids)
        sleep.assert_called_once_with(1)

    def test_dispatch_chunks_does_not_retry_permanent_bulk_item_errors(self) -> None:
        dispatch, client = _dispatch_with_bulk_client(
            [
                _bulk_response(
                    {
                        "_id": "chunk-1",
                        "status": 400,
                        "error": {
                            "type": "mapper_parsing_exception",
                            "reason": "bad document",
                        },
                    }
                )
            ]
        )

        with patch("dispatcher.elastic.elastic.time.sleep") as sleep:
            with self.assertRaisesRegex(
                RuntimeError,
                "Elasticsearch bulk chunk dispatch failed for 1 item",
            ):
                dispatch.dispatch_chunks([_chunk("chunk-1")])

        self.assertEqual([["chunk-1"]], client.bulk_chunk_ids)
        sleep.assert_not_called()

    def test_dispatch_chunks_fails_after_transient_bulk_retry_budget(self) -> None:
        dispatch, client = _dispatch_with_bulk_client(
            [
                _bulk_response(
                    {
                        "_id": "chunk-1",
                        "status": 500,
                        "error": {
                            "type": "inference_exception",
                            "reason": "node disconnected",
                        },
                    }
                ),
                _bulk_response(
                    {
                        "_id": "chunk-1",
                        "status": 500,
                        "error": {
                            "type": "inference_exception",
                            "reason": "node disconnected",
                        },
                    }
                ),
            ],
            bulk_max_retries=1,
        )

        with patch("dispatcher.elastic.elastic.time.sleep") as sleep:
            with self.assertRaisesRegex(
                RuntimeError,
                "Elasticsearch bulk chunk dispatch failed for 1 item",
            ):
                dispatch.dispatch_chunks([_chunk("chunk-1")])

        self.assertEqual([["chunk-1"], ["chunk-1"]], client.bulk_chunk_ids)
        sleep.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
