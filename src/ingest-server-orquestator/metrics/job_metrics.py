from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class JobStage(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PARSING = "parsing"
    CHUNKING = "chunking"
    DISPATCHING = "dispatching"
    DONE = "done"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stage_status(stage: JobStage | str) -> JobStatus:
    stage_value = str(stage)
    if stage_value == JobStage.QUEUED:
        return JobStatus.QUEUED
    if stage_value == JobStage.DONE:
        return JobStatus.DONE
    if stage_value == JobStage.FAILED:
        return JobStatus.FAILED
    return JobStatus.RUNNING


@dataclass(frozen=True, slots=True)
class JobMetrics:
    job_id: str
    file_name: str
    source: str
    size_bytes: int | None
    parser_type: str
    chunker_type: str
    status: str
    stage: str
    message: str
    pages_processed: int
    total_pages: int | None
    chunks_created: int
    chunks_dispatched: int
    error: str | None
    created_at: str
    started_at: str | None
    updated_at: str
    finished_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def queued(
        cls,
        *,
        job_id: str,
        file_name: str,
        source: str,
        size_bytes: int | None,
        parser_type: str,
        chunker_type: str,
    ) -> "JobMetrics":
        now = utc_now()
        return cls(
            job_id=job_id,
            file_name=file_name,
            source=source,
            size_bytes=size_bytes,
            parser_type=parser_type,
            chunker_type=chunker_type,
            status=JobStatus.QUEUED.value,
            stage=JobStage.QUEUED.value,
            message="Queued for processing.",
            pages_processed=0,
            total_pages=None,
            chunks_created=0,
            chunks_dispatched=0,
            error=None,
            created_at=now,
            started_at=None,
            updated_at=now,
            finished_at=None,
        )
