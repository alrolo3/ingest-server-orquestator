import sys
import threading
import unittest
from pathlib import Path
from queue import Empty
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from config.config import ServerConfig
from metrics.store import JobMetricsStore
from queues.domain.job import Job
from queues.queue_local import LocalQueue
from workers.inbound_worker import InboundWorker


class FakeFuture:
    def __init__(self) -> None:
        self._callbacks = []
        self._completed = False

    def add_done_callback(self, callback) -> None:
        self._callbacks.append(callback)
        if self._completed:
            callback(self)

    def complete(self) -> None:
        self._completed = True
        for callback in list(self._callbacks):
            callback(self)

    def result(self) -> None:
        return None


class FakeProcessPoolExecutor:
    def __init__(self, *args, **kwargs) -> None:
        self.submitted_jobs: list[Job] = []
        self.futures: list[FakeFuture] = []
        self.submitted = threading.Event()

    def submit(self, fn, job: Job, metrics_store: JobMetricsStore) -> FakeFuture:
        future = FakeFuture()
        self.submitted_jobs.append(job)
        self.futures.append(future)
        self.submitted.set()
        return future

    def shutdown(self, wait: bool = False, cancel_futures: bool = True) -> None:
        return None


class InboundWorkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._drain_local_queue()

    def tearDown(self) -> None:
        self._drain_local_queue()

    def test_single_worker_does_not_dequeue_next_job_until_current_future_completes(
        self,
    ) -> None:
        stop_event = threading.Event()
        fake_executor = FakeProcessPoolExecutor()

        with patch(
            "workers.inbound_worker.ProcessPoolExecutor",
            return_value=fake_executor,
        ):
            worker = InboundWorker(
                stop_event,
                JobMetricsStore(),
                server_config=self._server_config(),
            )

        first_job = self._job("job-1")
        second_job = self._job("job-2")
        worker.queue.put(first_job)
        worker.queue.put(second_job)

        worker_thread = threading.Thread(target=worker.run_forever)
        worker_thread.start()

        self.assertTrue(fake_executor.submitted.wait(timeout=1.0))
        self.assertEqual([first_job], fake_executor.submitted_jobs)
        self.assertEqual(1, worker.queue.queue.qsize())

        fake_executor.submitted.clear()
        fake_executor.futures[0].complete()

        self.assertTrue(fake_executor.submitted.wait(timeout=1.0))
        self.assertEqual([first_job, second_job], fake_executor.submitted_jobs)
        self.assertEqual(0, worker.queue.queue.qsize())

        fake_executor.futures[1].complete()
        stop_event.set()
        worker_thread.join(timeout=2.0)
        self.assertFalse(worker_thread.is_alive())

    def _server_config(self) -> ServerConfig:
        return ServerConfig(
            app_name="test",
            environment="test",
            inbound_queue_name="inbound",
            worker_max_workers=1,
            chunk_max_tokens=2048,
            tokenizer_path=Path("/tmp/tokenizer"),
            docling_artifacts_path=Path("/tmp/docling-artifacts"),
            docling_pp_layout_model_path=Path("/tmp/pp-doclayout-v3"),
        )

    def _job(self, job_id: str) -> Job:
        return Job(
            job_id=job_id,
            parser_type="docling",
            input_data={"file_path": f"/tmp/{job_id}.pdf"},
            chunker_type="token",
        )

    def _drain_local_queue(self) -> None:
        queue = LocalQueue().queue
        while True:
            try:
                queue.get(block=False)
                queue.task_done()
            except Empty:
                break


if __name__ == "__main__":
    unittest.main()
