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
                "source": "frontend",
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
        reporter.record_timing("parse", 2.0)
        reporter.record_timing("chunk", 0.5)
        reporter.mark_stage(JobStage.DISPATCHING, "Dispatching.")
        reporter.chunks_dispatched(7)
        reporter.record_timing("dispatch", 0.25)
        reporter.record_timing("total", 3.0)
        reporter.set_output(
            file_name="Sample output.md",
            path="/outputs/job-1/Sample output.md",
            url="/api/v1/ingest/jobs/job-1/output",
        )
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
        self.assertEqual(3.0, metrics["elapsed_seconds"])
        self.assertEqual(2.0, metrics["parse_seconds"])
        self.assertEqual(0.5, metrics["chunk_seconds"])
        self.assertEqual(0.25, metrics["dispatch_seconds"])
        self.assertEqual(1.5, metrics["pages_per_second"])
        self.assertEqual(14.0, metrics["chunks_per_second"])
        self.assertEqual(28.0, metrics["dispatch_chunks_per_second"])
        self.assertEqual("parse", metrics["slowest_stage"])
        self.assertEqual(
            {"parse": 2.0, "chunk": 0.5, "dispatch": 0.25},
            metrics["stage_timings"],
        )
        self.assertEqual("Sample output.md", metrics["output_file_name"])
        self.assertEqual("/outputs/job-1/Sample output.md", metrics["output_path"])
        self.assertEqual(
            "/api/v1/ingest/jobs/job-1/output",
            metrics["output_url"],
        )
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
