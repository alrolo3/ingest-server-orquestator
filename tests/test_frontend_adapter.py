import asyncio
import json
import sys
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, UploadFile

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from api.frontend_adapter import frontend_collections
from api.frontend_adapter import frontend_create_collection
from api.frontend_adapter import frontend_delete_collections
from api.frontend_adapter import frontend_document_summary
from api.frontend_adapter import frontend_documents
from api.frontend_adapter import frontend_generate
from api.frontend_adapter import frontend_task_status
from api.frontend_adapter import frontend_upload_documents
from config.config import ServerConfig
from metrics.store import JobMetricsStore


def _server_config() -> ServerConfig:
    return ServerConfig(
        app_name="test",
        environment="test",
        inbound_queue_name="queue",
        worker_max_workers=1,
        chunk_max_tokens=8192,
        tokenizer_path=Path("/tmp/tokenizer"),
        docling_artifacts_path=Path("/tmp/docling-artifacts"),
        docling_pp_layout_model_path=Path("/tmp/pp-doclayout-v3"),
        elastic_index_name="open-rag-embeddings-v4",
        elastic_hosts=["http://elastic:9200"],
        elastic_inference_id="qwen3-embedding-4b",
    )


def _request(
    store: JobMetricsStore | None = None,
    elasticsearch_client: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                server_config=_server_config(),
                metrics_store=store or JobMetricsStore(),
                frontend_collections={},
                frontend_deleted_collections=set(),
                elasticsearch_client=elasticsearch_client,
            )
        )
    )


def _upload_file(name: str, content: bytes = b"# Sample\n") -> UploadFile:
    return UploadFile(file=BytesIO(content), filename=name)


class FakeElasticsearch:
    def __init__(
        self,
        buckets: list[dict[str, object]],
        mappings: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self.buckets = buckets
        self.search_calls: list[dict[str, object]] = []
        self.indices = FakeIndices(mappings or {})

    def search(self, **kwargs: object) -> dict[str, object]:
        self.search_calls.append(kwargs)
        return {
            "aggregations": {
                "documents": {
                    "buckets": self.buckets,
                }
            }
        }


class FakeIndices:
    def __init__(self, mappings: dict[str, dict[str, object]]) -> None:
        self.mappings = mappings
        self.put_mapping_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []
        self.get_mapping_calls: list[dict[str, object]] = []

    def get_mapping(self, **kwargs: object) -> dict[str, object]:
        self.get_mapping_calls.append(kwargs)
        index = str(kwargs["index"])
        if "*" in index:
            prefix = index.split("*", 1)[0]
            return {
                name: mapping
                for name, mapping in self.mappings.items()
                if name.startswith(prefix)
            }
        return {
            index: self.mappings.get(index, {"mappings": {"_meta": {}}})
        }

    def put_mapping(self, **kwargs: object) -> None:
        self.put_mapping_calls.append(kwargs)
        index = str(kwargs["index"])
        self.mappings[index] = {
            "mappings": {
                "_meta": kwargs.get("_meta", {}),
            }
        }

    def delete(self, **kwargs: object) -> None:
        self.delete_calls.append(kwargs)
        self.mappings.pop(str(kwargs["index"]), None)


def _elastic_document_bucket(
    *,
    document_id: str = "doc-1",
    file_name: str = "manual.pdf",
    collection_name: str = "open-rag-embeddings-v4",
    task_id: str = "task-1",
    chunks: int = 3,
) -> dict[str, object]:
    return {
        "key": document_id,
        "doc_count": chunks,
        "first_ingested": {"value_as_string": "2026-06-12T10:00:00Z"},
        "last_ingested": {"value_as_string": "2026-06-12T10:02:00Z"},
        "total_pages": {"value": 12},
        "first_chunk": {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "document_id": document_id,
                            "source_file_name": file_name,
                            "collection_name": collection_name,
                            "task_id": task_id,
                            "source_size_bytes": 2048,
                            "title": "Manual",
                            "clean_title": "Manual",
                            "headings": ["Intro"],
                            "total_pages": 12,
                            "content": "Recovered first chunk text.",
                            "ingested_at": "2026-06-12T10:00:00Z",
                            "document_metadata": {"department": "ops"},
                        }
                    }
                ]
            }
        },
    }


class FrontendAdapterTest(unittest.TestCase):
    def test_collections_include_configured_elasticsearch_index(self) -> None:
        response = asyncio.run(frontend_collections(_request()))

        self.assertEqual(1, response["count"])
        collection = response["collections"][0]
        self.assertEqual("open-rag-embeddings-v4", collection["collection_name"])
        self.assertEqual("Active", collection["collection_info"]["status"])
        self.assertEqual("source", collection["metadata_schema"][0]["name"])

    def test_create_collection_creates_physical_open_rag_index(self) -> None:
        elasticsearch = FakeElasticsearch([])
        request = _request(elasticsearch_client=elasticsearch)
        created = []

        class FakeDispatch:
            def __init__(self, server_config, **kwargs) -> None:
                self.server_config = server_config
                self.kwargs = kwargs
                created.append(self)

            def close(self) -> None:
                return None

        with patch("api.frontend_adapter.ElasticsearchDispatch", FakeDispatch):
            response = asyncio.run(
                frontend_create_collection(
                    request,
                    {
                        "collection_name": "Vega Books",
                        "metadata_schema": [
                            {"name": "department", "type": "string"}
                        ],
                        "description": "Security books",
                    },
                )
            )

        self.assertEqual(
            "open-rag-vega-books",
            response["collection"]["collection_name"],
        )
        self.assertEqual(1, len(created))
        self.assertEqual("open-rag-vega-books", created[0].kwargs["index_name"])
        put_mapping = elasticsearch.indices.put_mapping_calls[0]
        self.assertEqual("open-rag-vega-books", put_mapping["index"])
        collection_meta = put_mapping["_meta"]["collection"]
        self.assertEqual("Security books", collection_meta["description"])
        self.assertEqual("department", collection_meta["metadata_schema"][0]["name"])

    def test_collections_recover_open_rag_indices_from_elasticsearch(self) -> None:
        elasticsearch = FakeElasticsearch(
            [],
            mappings={
                "open-rag-books": {
                    "mappings": {
                        "_meta": {
                            "collection": {
                                "metadata_schema": [
                                    {"name": "department", "type": "string"}
                                ],
                                "description": "Books index",
                                "status": "Active",
                            }
                        }
                    }
                },
                "case-rag": {
                    "mappings": {
                        "_meta": {
                            "collection": {"description": "not a frontend collection"}
                        }
                    }
                },
            },
        )
        response = asyncio.run(frontend_collections(_request(elasticsearch_client=elasticsearch)))

        names = [collection["collection_name"] for collection in response["collections"]]
        self.assertIn("open-rag-embeddings-v4", names)
        self.assertIn("open-rag-books", names)
        self.assertNotIn("case-rag", names)
        books = next(
            collection
            for collection in response["collections"]
            if collection["collection_name"] == "open-rag-books"
        )
        self.assertEqual("Books index", books["collection_info"]["description"])
        self.assertEqual("department", books["metadata_schema"][0]["name"])

    def test_upload_documents_creates_task_backed_by_ingest_jobs(self) -> None:
        store = JobMetricsStore()
        request = _request(store)

        with TemporaryDirectory() as temp_dir:
            with (
                patch("api.frontend_adapter.UPLOAD_DIR", Path(temp_dir)),
                patch("api.frontend_adapter.local_queue.put") as put_item,
            ):
                upload_response = asyncio.run(
                    frontend_upload_documents(
                        request,
                        documents=[
                            _upload_file("one.md", b"# One\n"),
                            _upload_file("two.md", b"# Two\n"),
                        ],
                        data=json.dumps(
                            {
                                "collection_name": "manuals",
                                "custom_metadata": [
                                    {
                                        "filename": "one.md",
                                        "metadata": {"department": "ops"},
                                    }
                                ],
                            }
                        ),
                        blocking=False,
                    )
                )

        self.assertEqual("open-rag-manuals", upload_response["collection_name"])
        self.assertEqual(2, upload_response["total_documents"])
        self.assertEqual(2, put_item.call_count)
        first_job = put_item.call_args_list[0].args[0]
        self.assertEqual("open-rag-manuals", first_job.input_data["collection_name"])
        self.assertEqual("open-rag-manuals", first_job.settings["elastic_index_name"])

        task_id = upload_response["task_id"]
        status_response = asyncio.run(frontend_task_status(request, task_id))
        self.assertEqual("PENDING", status_response["state"])
        self.assertEqual("open-rag-manuals", status_response["collection_name"])
        self.assertEqual(["one.md", "two.md"], status_response["documents"])
        self.assertEqual(2, status_response["result"]["total_documents"])

        documents_response = asyncio.run(
            frontend_documents(request, collection_name="manuals")
        )
        self.assertEqual(2, documents_response["total_documents"])
        first_document = documents_response["documents"][0]
        self.assertEqual("one.md", first_document["document_name"])
        self.assertEqual("ops", first_document["metadata"]["department"])

    def test_documents_recover_from_elasticsearch_when_metrics_are_empty(self) -> None:
        elasticsearch = FakeElasticsearch([_elastic_document_bucket()])
        request = _request(JobMetricsStore(), elasticsearch_client=elasticsearch)

        collections_response = asyncio.run(frontend_collections(request))
        collection = collections_response["collections"][0]
        self.assertEqual("open-rag-embeddings-v4", collection["collection_name"])
        self.assertEqual(1, collection["collection_info"]["number_of_files"])
        self.assertEqual(3, collection["num_entities"])

        documents_response = asyncio.run(
            frontend_documents(request, collection_name="open-rag-embeddings-v4")
        )

        self.assertEqual(1, documents_response["total_documents"])
        document = documents_response["documents"][0]
        self.assertEqual("manual.pdf", document["document_name"])
        self.assertEqual("doc-1", document["metadata"]["job_id"])
        self.assertEqual("done", document["metadata"]["status"])
        self.assertEqual("elasticsearch", document["metadata"]["recovered_from"])
        self.assertEqual("ops", document["metadata"]["department"])
        self.assertEqual(3, document["document_info"]["total_elements"])
        self.assertEqual(12, document["document_info"]["total_pages"])
        self.assertEqual("open-rag-embeddings-v4", elasticsearch.search_calls[-1]["index"])

    def test_summary_recovers_from_elasticsearch_excerpt(self) -> None:
        elasticsearch = FakeElasticsearch([_elastic_document_bucket()])
        request = _request(JobMetricsStore(), elasticsearch_client=elasticsearch)

        response = asyncio.run(
            frontend_document_summary(
                request,
                collection_name="open-rag-embeddings-v4",
                file_name="manual.pdf",
            )
        )

        self.assertEqual("SUCCESS", response["status"])
        self.assertEqual("Recovered first chunk text.", response["summary"])

    def test_delete_collection_deletes_physical_index(self) -> None:
        store = JobMetricsStore()
        elasticsearch = FakeElasticsearch(
            [],
            mappings={"open-rag-books": {"mappings": {"_meta": {}}}},
        )
        request = _request(store, elasticsearch_client=elasticsearch)

        response = asyncio.run(frontend_delete_collections(request, ["books"]))

        self.assertEqual(["open-rag-books"], response["collections"])
        self.assertEqual(
            {"index": "open-rag-books", "ignore_unavailable": True},
            elasticsearch.indices.delete_calls[0],
        )

    def test_delete_collection_rejects_default_index(self) -> None:
        request = _request(elasticsearch_client=FakeElasticsearch([]))

        with self.assertRaises(HTTPException) as exc:
            asyncio.run(
                frontend_delete_collections(
                    request,
                    ["open-rag-embeddings-v4"],
                )
            )

        self.assertEqual(400, exc.exception.status_code)

    def test_generate_returns_nvidia_streaming_contract(self) -> None:
        response = asyncio.run(
            frontend_generate(
                _request(),
                payload={
                    "messages": [
                        {"role": "user", "content": "What can this server do?"}
                    ],
                    "collection_names": ["open-rag-embeddings-v4"],
                },
            )
        )

        async def collect() -> str:
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
            return "".join(chunks)

        body = asyncio.run(collect())

        self.assertIn("data: ", body)
        self.assertIn("finish_reason", body)
        self.assertIn("not configured", body)


if __name__ == "__main__":
    unittest.main()
