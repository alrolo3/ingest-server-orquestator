# queues/workers/inbound_worker.py

import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
import logging
from queue import Empty
from threading import BoundedSemaphore, Event

from config.config import ServerConfig, get_server_config
from metrics.job_metrics import JobStage
from metrics.progress import ProgressReporter
from metrics.store import JobMetricsStore
from queues.queue_local import LocalQueue
from queues.domain.job import Job
from workers.job_runner import job_runner


LOGGER = logging.getLogger("ingest-server-orquestator.worker")


class InboundWorker:
    def __init__(
        self,
        stop_event: Event,
        metrics_store: JobMetricsStore,
        server_config: ServerConfig | None = None,
    ) -> None:
        self.stop_event = stop_event
        self.queue = LocalQueue()
        self.metrics_store = metrics_store
        self.server_config = server_config or get_server_config()
        self.executor_slots = BoundedSemaphore(self.server_config.worker_max_workers)

        self.process_pool = ProcessPoolExecutor(
            max_workers=self.server_config.worker_max_workers,
            mp_context=mp.get_context("spawn"),
            max_tasks_per_child=1,
        )
        LOGGER.info(
            "Inbound worker initialized max_workers=%s",
            self.server_config.worker_max_workers,
        )

    def _on_job_done(self, job: Job, future):
        try:
            future.result()
            LOGGER.info("Job completed successfully job_id=%s", job.job_id)
        except Exception as exc:
            ProgressReporter(job.job_id, self.metrics_store).mark_failed(
                str(exc),
                stage=JobStage.FAILED,
            )
            LOGGER.exception("Job failed job_id=%s", job.job_id)

    def shutdown(self) -> None:
        LOGGER.info("Inbound worker shutting down")
        self.process_pool.shutdown(wait=False, cancel_futures=True)

    def run_forever(self) -> None:
        LOGGER.info("Inbound worker loop started")
        while not self.stop_event.is_set():
            if not self.executor_slots.acquire(timeout=0.5):
                continue

            try:
                job = self.queue.get(timeout=0.5)
            except Empty:
                self.executor_slots.release()
                continue

            LOGGER.info("Dequeued ingest job job_id=%s", job.job_id)
            try:
                future = self.process_pool.submit(job_runner, job, self.metrics_store)
            except Exception:
                self.executor_slots.release()
                self.queue.queue.task_done()
                raise

            future.add_done_callback(lambda _: self.executor_slots.release())
            future.add_done_callback(lambda _: self.queue.queue.task_done())
            future.add_done_callback(
                lambda completed_future, queued_job=job: self._on_job_done(
                    queued_job,
                    completed_future,
                )
            )
