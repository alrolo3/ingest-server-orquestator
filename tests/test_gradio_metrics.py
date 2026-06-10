import sys
import unittest
from pathlib import Path

GRADIO_DIR = Path(__file__).resolve().parents[1] / "gradio_file_ingest"
sys.path.insert(0, str(GRADIO_DIR))

import app as gradio_app


class GradioMetricsTest(unittest.TestCase):
    def test_job_tables_group_active_processed_and_failed_jobs(self) -> None:
        summary, active_rows, processed_rows, error_rows = gradio_app._job_tables(
            [
                {
                    "file_name": "queued.pdf",
                    "status": "queued",
                    "stage": "queued",
                    "pages_processed": 0,
                    "total_pages": None,
                    "chunks_created": 0,
                    "chunks_dispatched": 0,
                    "message": "Queued.",
                    "updated_at": "t1",
                },
                {
                    "file_name": "done.pdf",
                    "status": "done",
                    "stage": "done",
                    "pages_processed": 4,
                    "total_pages": 4,
                    "chunks_created": 8,
                    "chunks_dispatched": 8,
                    "elapsed_seconds": 12.3,
                    "slowest_stage": "parse",
                    "pages_per_second": 0.33,
                    "chunks_per_second": 1.2,
                    "message": "Job done.",
                    "finished_at": "t2",
                },
                {
                    "file_name": "bad.pdf",
                    "status": "failed",
                    "stage": "parsing",
                    "pages_processed": 1,
                    "total_pages": 4,
                    "error": "parse failed",
                    "finished_at": "t3",
                },
            ]
        )

        self.assertEqual("Jobs: 3 total, 1 active, 1 done, 1 failed.", summary)
        self.assertEqual("queued.pdf", active_rows[0][0])
        self.assertEqual("0/?", active_rows[0][3])
        self.assertEqual("done.pdf", processed_rows[0][0])
        self.assertEqual("8/8", processed_rows[0][3])
        self.assertEqual("12.3s", processed_rows[0][4])
        self.assertEqual("parse", processed_rows[0][5])
        self.assertEqual("0.33 p/s, 1.20 c/s", processed_rows[0][6])
        self.assertEqual("bad.pdf", error_rows[0][0])
        self.assertEqual("parse failed", error_rows[0][5])

    def test_jobs_url_uses_backend_base_and_default_jobs_path(self) -> None:
        self.assertEqual(
            "http://backend/api/v1/ingest/jobs",
            gradio_app._jobs_url("http://backend/"),
        )


if __name__ == "__main__":
    unittest.main()
