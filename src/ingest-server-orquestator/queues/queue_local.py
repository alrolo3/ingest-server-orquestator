from __future__ import annotations

from queue import Queue
from typing import Any

from queues.domain.job import Job


class SingletonMeta(type):
    _instances: dict[type, Any] = {}

    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)

        return cls._instances[cls]


class LocalQueue(metaclass=SingletonMeta):
    def __init__(self) -> None:
        self._queue: Queue[Job] = Queue()

    @property
    def queue(self) -> Queue[Job]:
        return self._queue

    def put(self, item: Job) -> None:
        self._queue.put(item)

    def get(self, block: bool = True, timeout: float | None = None) -> Job:
        if timeout is None:
            return self._queue.get(block=block)

        return self._queue.get(block=block, timeout=timeout)


def get_local_queue() -> Queue[Job]:
    return LocalQueue().queue


def put_item(item: Job) -> None:
    LocalQueue().put(item)


def get_item(block: bool = True, timeout: float | None = None) -> Job:
    return LocalQueue().get(block=block, timeout=timeout)
