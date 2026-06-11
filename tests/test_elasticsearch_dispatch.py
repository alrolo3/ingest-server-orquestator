import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from dispatcher.elastic.elastic import ElasticsearchDispatch, OPEN_RAG_PIPELINE


class FakeIndices:
    def __init__(self, mapping: dict[str, object]) -> None:
        self.mapping = mapping
        self.put_mapping_calls: list[dict[str, object]] = []

    def get_mapping(self, *, index: str) -> dict[str, object]:
        return self.mapping

    def put_mapping(self, **kwargs: object) -> None:
        self.put_mapping_calls.append(kwargs)


class FakeClient:
    def __init__(self, mapping: dict[str, object]) -> None:
        self.indices = FakeIndices(mapping)


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

    def test_ensure_index_mappings_adds_sparse_semantic_fields_when_missing(
        self,
    ) -> None:
        dispatch = ElasticsearchDispatch.model_construct(
            index_name="rag-index",
            inference_id="custom-inference",
        )
        dispatch._client = FakeClient(
            {
                "rag-index": {
                    "mappings": {
                        "properties": {
                            "content": {"type": "semantic_text"},
                        }
                    }
                }
            }
        )

        dispatch._ensure_index_mappings()

        calls = dispatch._client.indices.put_mapping_calls
        self.assertEqual(1, len(calls))
        self.assertEqual("rag-index", calls[0]["index"])
        self.assertEqual(
            ["content_sparse", "clean_title", "headings"],
            list(calls[0]["properties"]),
        )
        for mapping in calls[0]["properties"].values():
            self.assertEqual("semantic_text", mapping["type"])
            self.assertEqual(
                "opensearch-multilingual-neural-sparse",
                mapping["inference_id"],
            )
            self.assertEqual({"strategy": "none"}, mapping["chunking_settings"])
            self.assertNotIn("index_options", mapping)
            self.assertNotIn("model_settings", mapping)

    def test_ensure_index_mappings_adds_only_missing_sparse_fields(
        self,
    ) -> None:
        dispatch = ElasticsearchDispatch.model_construct(
            index_name="rag-index",
            inference_id="custom-inference",
        )
        dispatch._client = FakeClient(
            {
                "rag-index": {
                    "mappings": {
                        "properties": {
                            "content": {"type": "semantic_text"},
                            "content_sparse": {"type": "semantic_text"},
                            "clean_title": {"type": "semantic_text"},
                        }
                    }
                }
            }
        )

        dispatch._ensure_index_mappings()

        calls = dispatch._client.indices.put_mapping_calls
        self.assertEqual(1, len(calls))
        self.assertEqual(["headings"], list(calls[0]["properties"]))

    def test_ensure_index_mappings_skips_existing_sparse_fields(self) -> None:
        dispatch = ElasticsearchDispatch.model_construct(
            index_name="rag-index",
            inference_id="custom-inference",
        )
        dispatch._client = FakeClient(
            {
                "rag-index": {
                    "mappings": {
                        "properties": {
                            "content": {"type": "semantic_text"},
                            "content_sparse": {"type": "semantic_text"},
                            "clean_title": {"type": "semantic_text"},
                            "headings": {"type": "semantic_text"},
                        }
                    }
                }
            }
        )

        dispatch._ensure_index_mappings()

        self.assertEqual([], dispatch._client.indices.put_mapping_calls)

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

        self.assertIn("ctx.content_sparse = escapeText(ctx.content_sparse)", escape_source)
        self.assertIn("ctx.clean_title = escapeText(ctx.clean_title)", escape_source)
        self.assertIn("for (def heading : ctx.headings)", escape_source)
        self.assertIn("String cleanedTitle = cleanTitle(ctx.clean_title)", normalization_source)
        self.assertIn("String sourceTitle = cleanTitle(ctx.source_file_name)", normalization_source)
        self.assertIn("ctx.headings = normalizeTextList(ctx.headings)", normalization_source)
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


if __name__ == "__main__":
    unittest.main()
