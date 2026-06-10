import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from dispatcher.elastic.elastic import ElasticsearchDispatch


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

    def test_ensure_index_mappings_skips_existing_title_semantic(self) -> None:
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

        self.assertEqual([], dispatch._client.indices.put_mapping_calls)


if __name__ == "__main__":
    unittest.main()
