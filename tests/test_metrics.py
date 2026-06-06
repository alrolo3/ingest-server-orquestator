import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from metrics.job_metrics import JobStage
from metrics.progress import ProgressReporter
from metrics.store import JobMetricsStore
from queues.domain.job import Job


class JobMetricsStoreTest(unittest.TestCase):
    def test_reporter_tracks_successful_lifecycle(self) -> None:
        store = JobMetricsStore()
        job = Job.create(
            parser_type="docling",
            input_data={
                "file_name": "sample.pdf",
                "source": "gradio",
                "size_bytes": 42,
            },
            chunker_type="token",
        )
        store.create_for_job(job)
        reporter = ProgressReporter(job.job_id, store)

        reporter.mark_stage(JobStage.PARSING, "Parsing.")
        reporter.set_total_pages(3)
        reporter.page_processed(1)
        reporter.page_processed(2)
        reporter.chunks_created(7)
        reporter.mark_stage(JobStage.DISPATCHING, "Dispatching.")
        reporter.chunks_dispatched(7)
        reporter.mark_done()

        metrics = store.get(job.job_id)
        self.assertIsNotNone(metrics)
        assert metrics is not None
        self.assertEqual("done", metrics["status"])
        self.assertEqual("done", metrics["stage"])
        self.assertEqual(2, metrics["pages_processed"])
        self.assertEqual(3, metrics["total_pages"])
        self.assertEqual(7, metrics["chunks_created"])
        self.assertEqual(7, metrics["chunks_dispatched"])
        self.assertEqual("Job done: chunks sent to Elasticsearch.", metrics["message"])
        self.assertIsNone(metrics["error"])
        self.assertIsNotNone(metrics["finished_at"])

    def test_reporter_tracks_failure(self) -> None:
        store = JobMetricsStore()
        job = Job.create(
            parser_type="docling",
            input_data={"file_name": "bad.pdf"},
            chunker_type="token",
        )
        store.create_for_job(job)

        ProgressReporter(job.job_id, store).mark_failed(
            "parse failed",
            stage=JobStage.PARSING,
        )

        metrics = store.get(job.job_id)
        self.assertIsNotNone(metrics)
        assert metrics is not None
        self.assertEqual("failed", metrics["status"])
        self.assertEqual("parsing", metrics["stage"])
        self.assertEqual("parse failed", metrics["error"])

    def test_list_filters_status_and_stage(self) -> None:
        store = JobMetricsStore()
        queued = Job.create(
            parser_type="docling",
            input_data={"file_name": "queued.pdf"},
            chunker_type="token",
        )
        failed = Job.create(
            parser_type="docling",
            input_data={"file_name": "failed.pdf"},
            chunker_type="token",
        )
        store.create_for_job(queued)
        store.create_for_job(failed)
        ProgressReporter(failed.job_id, store).mark_failed(
            "boom",
            stage=JobStage.CHUNKING,
        )

        failed_jobs = store.list(status="failed")
        chunking_jobs = store.list(stage="chunking")

        self.assertEqual([failed.job_id], [job["job_id"] for job in failed_jobs])
        self.assertEqual([failed.job_id], [job["job_id"] for job in chunking_jobs])


if __name__ == "__main__":
    unittest.main()
