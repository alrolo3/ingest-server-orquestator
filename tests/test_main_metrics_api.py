import asyncio
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SRC_DIR))

from metrics.job_metrics import JobStage
from metrics.progress import ProgressReporter
from metrics.store import JobMetricsStore
from queues.domain.job import Job
from src.main import ingest_job, ingest_job_output, ingest_jobs


class MetricsApiTest(unittest.TestCase):
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
