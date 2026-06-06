import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SRC_DIR))

from metrics.job_metrics import JobStage
from metrics.progress import ProgressReporter
from metrics.store import JobMetricsStore
from queues.domain.job import Job
from src.main import ingest_job, ingest_jobs


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


if __name__ == "__main__":
    unittest.main()
