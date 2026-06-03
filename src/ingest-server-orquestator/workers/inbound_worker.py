# queues/workers/inbound_worker.py

import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from queue import Empty
from threading import Event

from queues.queue_local import LocalQueue
from workers.job_runner import job_runner


class InboundWorker:
    def __init__(self, stop_event: Event) -> None:
        self.stop_event = stop_event
        self.queue = LocalQueue()

        self.process_pool = ProcessPoolExecutor(
            max_workers=2,
            mp_context=mp.get_context("spawn"),
            max_tasks_per_child=10,
        )

    def run_forever(self) -> None:
        while not self.stop_event.is_set():
            try:
                job = self.queue.get(timeout=0.5)
            except Empty:
                continue

            future = self.process_pool.submit(job_runner, job)
            future.add_done_callback(lambda _: self.queue.queue.task_done())