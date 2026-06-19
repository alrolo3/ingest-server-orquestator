import asyncio
from io import BytesIO
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, UploadFile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SRC_DIR))

from metrics.job_metrics import JobStage
from metrics.progress import ProgressReporter
from metrics.store import JobMetricsStore
from queues.domain.job import Job
from src.main import (
    _ensure_elasticsearch_index,
    ingest_case,
    ingest_file,
    ingest_job,
    ingest_job_output,
    ingest_jobs,
)


class FakeQueue:
    def __init__(self) -> None:
        self.jobs = []

    def put(self, job) -> None:
        self.jobs.append(job)


class MetricsApiTest(unittest.TestCase):
    def test_startup_elasticsearch_ensure_closes_dispatcher(self) -> None:
        created = []

        class FakeDispatch:
            def __init__(self, server_config) -> None:
                self.server_config = server_config
                self.closed = False
                created.append(self)

            def close(self) -> None:
                self.closed = True

        config = object()
        with patch("src.main.ElasticsearchDispatch", FakeDispatch):
            _ensure_elasticsearch_index(config)

        self.assertEqual(1, len(created))
        self.assertIs(config, created[0].server_config)
        self.assertTrue(created[0].closed)

    def test_ingest_case_queues_markdown_job_to_case_rag(self) -> None:
        store = JobMetricsStore()
        config = SimpleNamespace(inbound_queue_name="inbound")
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(server_config=config, metrics_store=store)
            )
        )
        queue = FakeQueue()
        payload = {
            "content": "# CASE-1\nInvestigate alert.",
            "title": "CASE-1",
            "case_id": "CASE-1",
            "severity": "high",
        }

        with TemporaryDirectory() as temp_dir:
            with (
                patch("src.main.UPLOAD_DIR", Path(temp_dir)),
                patch("src.main.local_queue", queue),
            ):
                response = asyncio.run(ingest_case(request, payload))

                self.assertEqual(1, len(queue.jobs))
                job = queue.jobs[0]
                stored_path = Path(job.input_data["file_path"])
                self.assertEqual(
                    payload["content"],
                    stored_path.read_text(encoding="utf-8"),
                )

        self.assertEqual("inbound", response["queue"])
        self.assertEqual("text/markdown", job.input_data["mime_type"])
        self.assertEqual("CASE-1.md", job.input_data["file_name"])
        self.assertEqual("elastic-workflow", job.input_data["source"])
        self.assertEqual("case-rag", job.input_data["collection_name"])
        self.assertEqual("case-rag", job.settings["elastic_index_name"])
        self.assertNotIn("content", job.input_data["document_metadata"])
        self.assertEqual("high", job.input_data["document_metadata"]["severity"])

        record = store.get(job.job_id)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual("case-rag", record["collection_name"])
        self.assertEqual("high", record["document_metadata"]["severity"])

    def test_ingest_case_rejects_missing_or_empty_content(self) -> None:
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    server_config=SimpleNamespace(inbound_queue_name="inbound"),
                    metrics_store=JobMetricsStore(),
                )
            )
        )

        for payload in ({}, {"content": ""}, {"content": "   "}):
            with self.subTest(payload=payload):
                with self.assertRaises(HTTPException) as exc:
                    asyncio.run(ingest_case(request, payload))
                self.assertEqual(400, exc.exception.status_code)

    def test_ingest_file_does_not_set_case_index_override(self) -> None:
        store = JobMetricsStore()
        config = SimpleNamespace(inbound_queue_name="inbound")
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(server_config=config, metrics_store=store)
            )
        )
        queue = FakeQueue()
        file = UploadFile(file=BytesIO(b"# File\n"), filename="sample.md")

        with TemporaryDirectory() as temp_dir:
            with (
                patch("src.main.UPLOAD_DIR", Path(temp_dir)),
                patch("src.main.local_queue", queue),
            ):
                asyncio.run(ingest_file(request, file=file, source="api"))

        self.assertEqual(1, len(queue.jobs))
        self.assertNotIn("elastic_index_name", queue.jobs[0].settings)

    def test_list_and_detail_metrics(self) -> None:
        store = JobMetricsStore()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(metrics_store=store)))
        job = Job.create(
            parser_type="docling",
            input_data={
                "file_name": "sample.pdf",
                "source": "test",
                "size_bytes": 10,
            },
            chunker_type="token",
        )
        store.create_for_job(job)
        ProgressReporter(job.job_id, store).mark_stage(
            JobStage.PARSING,
            "Parsing document.",
        )

        list_response = asyncio.run(ingest_jobs(request, limit=100))
        detail_response = asyncio.run(ingest_job(request, job.job_id))

        jobs = list_response["jobs"]
        self.assertEqual(1, len(jobs))
        self.assertEqual(job.job_id, jobs[0]["job_id"])
        self.assertEqual("parsing", jobs[0]["stage"])

        self.assertEqual(job.job_id, detail_response["job"]["job_id"])

        with self.assertRaises(HTTPException) as exc:
            asyncio.run(ingest_job(request, "missing"))
        self.assertEqual(404, exc.exception.status_code)

    def test_download_job_output(self) -> None:
        store = JobMetricsStore()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(metrics_store=store)))
        job = Job.create(
            parser_type="docling",
            input_data={"file_name": "sample.pdf"},
            chunker_type="token",
        )
        store.create_for_job(job)

        with TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            output_path = output_root / job.job_id / "Sample output.md"
            output_path.parent.mkdir(parents=True)
            output_path.write_text("# Sample\n", encoding="utf-8")
            store.update(
                job.job_id,
                output_file_name="Sample output.md",
                output_path=str(output_path),
                output_url=f"/api/v1/ingest/jobs/{job.job_id}/output",
            )
            detail_response = asyncio.run(ingest_job(request, job.job_id))

            with patch("src.main.OUTPUT_DIR", output_root):
                response = asyncio.run(ingest_job_output(request, job.job_id))

        self.assertNotIn("output_path", detail_response["job"])
        self.assertEqual("Sample output.md", detail_response["job"]["output_file_name"])
        self.assertEqual(output_path, response.path)
        self.assertEqual("text/markdown", response.media_type)
        self.assertIn("Sample%20output.md", response.headers["content-disposition"])

    def test_download_job_output_rejects_missing_file(self) -> None:
        store = JobMetricsStore()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(metrics_store=store)))
        job = Job.create(
            parser_type="docling",
            input_data={"file_name": "sample.pdf"},
            chunker_type="token",
        )
        store.create_for_job(job)
        store.update(
            job.job_id,
            output_file_name="Sample output.md",
            output_path="/outputs/missing.md",
        )

        with self.assertRaises(HTTPException) as exc:
            asyncio.run(ingest_job_output(request, job.job_id))

        self.assertEqual(404, exc.exception.status_code)


if __name__ == "__main__":
    unittest.main()
