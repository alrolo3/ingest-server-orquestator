import asyncio
import json
import sys
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import UploadFile

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from api.frontend_adapter import frontend_collections
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


def _request(store: JobMetricsStore | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                server_config=_server_config(),
                metrics_store=store or JobMetricsStore(),
                frontend_collections={},
                frontend_deleted_collections=set(),
            )
        )
    )


def _upload_file(name: str, content: bytes = b"# Sample\n") -> UploadFile:
    return UploadFile(file=BytesIO(content), filename=name)


class FrontendAdapterTest(unittest.TestCase):
    def test_collections_include_configured_elasticsearch_index(self) -> None:
        response = asyncio.run(frontend_collections(_request()))

        self.assertEqual(1, response["count"])
        collection = response["collections"][0]
        self.assertEqual("open-rag-embeddings-v4", collection["collection_name"])
        self.assertEqual("Active", collection["collection_info"]["status"])
        self.assertEqual("source", collection["metadata_schema"][0]["name"])

    def test_upload_documents_creates_task_backed_by_ingest_jobs(self) -> None:
        store = JobMetricsStore()
        request = _request(store)

        with TemporaryDirectory() as temp_dir:
            with (
                patch("api.frontend_adapter.UPLOAD_DIR", Path(temp_dir)),
                patch("api.frontend_adapter.put_item") as put_item,
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

        self.assertEqual("manuals", upload_response["collection_name"])
        self.assertEqual(2, upload_response["total_documents"])
        self.assertEqual(2, put_item.call_count)

        task_id = upload_response["task_id"]
        status_response = asyncio.run(frontend_task_status(request, task_id))
        self.assertEqual("PENDING", status_response["state"])
        self.assertEqual(["one.md", "two.md"], status_response["documents"])
        self.assertEqual(2, status_response["result"]["total_documents"])

        documents_response = asyncio.run(
            frontend_documents(request, collection_name="manuals")
        )
        self.assertEqual(2, documents_response["total_documents"])
        first_document = documents_response["documents"][0]
        self.assertEqual("one.md", first_document["document_name"])
        self.assertEqual("ops", first_document["metadata"]["department"])

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
