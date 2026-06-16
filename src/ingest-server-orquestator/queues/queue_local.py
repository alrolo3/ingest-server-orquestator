from __future__ import annotations

from queue import Queue

from queues.domain.job import Job


local_queue: Queue[Job] = Queue()
