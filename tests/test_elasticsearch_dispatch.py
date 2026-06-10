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
        self.assertNotIn("lastIndexOf('/')", normalization_source)
        self.assertNotIn("lastIndexOf('\\\\')", normalization_source)
        self.assertIn('lastIndexOf("/")', normalization_source)
        self.assertIn('lastIndexOf("\\\\")', normalization_source)

    def test_ensure_index_mappings_adds_title_semantic_when_missing(self) -> None:
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
        title_mapping = calls[0]["properties"]["title_semantic"]
        self.assertEqual("semantic_text", title_mapping["type"])
        self.assertEqual("custom-inference", title_mapping["inference_id"])
        sparse_mapping = calls[0]["properties"]["title_sparse"]
        self.assertEqual("semantic_text", sparse_mapping["type"])
        self.assertEqual(
            "opensearch-multilingual-neural-sparse",
            sparse_mapping["inference_id"],
        )
        self.assertEqual(
            {"strategy": "none"},
            sparse_mapping["chunking_settings"],
        )
        self.assertNotIn("index_options", sparse_mapping)

    def test_ensure_index_mappings_adds_title_sparse_when_title_semantic_exists(
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
                            "title_semantic": {"type": "semantic_text"},
                        }
                    }
                }
            }
        )

        dispatch._ensure_index_mappings()

        calls = dispatch._client.indices.put_mapping_calls
        self.assertEqual(1, len(calls))
        self.assertEqual(["title_sparse"], list(calls[0]["properties"]))

    def test_ensure_index_mappings_skips_existing_title_fields(self) -> None:
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
                            "title_semantic": {"type": "semantic_text"},
                            "title_sparse": {"type": "semantic_text"},
                        }
                    }
                }
            }
        )

        dispatch._ensure_index_mappings()

        self.assertEqual([], dispatch._client.indices.put_mapping_calls)

    def test_pipeline_populates_title_sparse_from_clean_title(self) -> None:
        script_sources = [
            processor["script"]["source"]
            for processor in OPEN_RAG_PIPELINE["processors"]
            if "script" in processor
        ]
        escape_source = next(source for source in script_sources if "$ {" in source)
        normalization_source = next(
            source for source in script_sources if "String cleanTitle" in source
        )

        self.assertIn("ctx.title_sparse.replace", escape_source)
        self.assertIn("String sparseTitle = cleanTitle(ctx.title_sparse)", normalization_source)
        self.assertIn("ctx.title_sparse = sparseTitle", normalization_source)


if __name__ == "__main__":
    unittest.main()
