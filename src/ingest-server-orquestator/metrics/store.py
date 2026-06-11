from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from metrics.job_metrics import JobMetrics, JobStage, JobStatus, stage_status, utc_now
from queues.domain.job import Job


class JobMetricsStore:
    """Process-safe job metrics facade over a plain or manager-backed mapping."""

    def __init__(
        self,
        records: MutableMapping[str, dict[str, Any]] | None = None,
    ) -> None:
        self._records: MutableMapping[str, dict[str, Any]] = (
            records if records is not None else {}
        )

    def create_for_job(self, job: Job) -> dict[str, Any]:
        input_data = job.input_data
        metrics = JobMetrics.queued(
            job_id=job.job_id,
            file_name=str(input_data.get("file_name") or ""),
            source=str(input_data.get("source") or ""),
            size_bytes=_optional_int(input_data.get("size_bytes")),
            parser_type=job.parser_type,
            chunker_type=job.chunker_type,
        ).to_dict()
        self._records[job.job_id] = metrics
        return dict(metrics)

    def ensure_job(self, job: Job) -> dict[str, Any]:
        existing = self.get(job.job_id)
        if existing is not None:
            return existing
        return self.create_for_job(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        record = self._records.get(job_id)
        if record is None:
            return None
        return dict(record)

    def list(
        self,
        *,
        status: str | None = None,
        stage: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        records = [dict(record) for record in self._records.values()]
        if status:
            records = [record for record in records if record.get("status") == status]
        if stage:
            records = [record for record in records if record.get("stage") == stage]
        records.sort(key=lambda record: str(record.get("created_at") or ""), reverse=True)
        if limit is not None and limit > 0:
            return records[:limit]
        return records

    def mark_stage(
        self,
        job_id: str,
        stage: JobStage | str,
        *,
        message: str | None = None,
    ) -> dict[str, Any]:
        stage_value = str(stage)
        status = stage_status(stage_value)
        changes: dict[str, Any] = {
            "stage": stage_value,
            "status": status.value,
        }
        if message is not None:
            changes["message"] = message
        if status == JobStatus.RUNNING:
            record = self.get(job_id)
            if record and record.get("started_at") is None:
                changes["started_at"] = utc_now()
        return self.update(job_id, **changes)

    def update(self, job_id: str, **changes: Any) -> dict[str, Any]:
        record = self.get(job_id)
        if record is None:
            now = utc_now()
            record = {
                "job_id": job_id,
                "file_name": "",
                "source": "",
                "size_bytes": None,
                "parser_type": "",
                "chunker_type": "",
                "status": JobStatus.RUNNING.value,
                "stage": JobStage.RUNNING.value,
                "message": "",
                "pages_processed": 0,
                "total_pages": None,
                "chunks_created": 0,
                "chunks_dispatched": 0,
                "elapsed_seconds": None,
                "parse_seconds": None,
                "chunk_seconds": None,
                "dispatch_seconds": None,
                "pages_per_second": None,
                "chunks_per_second": None,
                "dispatch_chunks_per_second": None,
                "slowest_stage": None,
                "stage_timings": {},
                "output_file_name": None,
                "output_path": None,
                "output_url": None,
                "error": None,
                "created_at": now,
                "started_at": now,
                "updated_at": now,
                "finished_at": None,
            }

        for key, value in changes.items():
            if isinstance(value, (JobStage, JobStatus)):
                value = value.value
            record[key] = value
        record["updated_at"] = utc_now()
        self._records[job_id] = record
        return dict(record)

    def mark_done(self, job_id: str, *, message: str) -> dict[str, Any]:
        now = utc_now()
        return self.update(
            job_id,
            status=JobStatus.DONE.value,
            stage=JobStage.DONE.value,
            message=message,
            error=None,
            finished_at=now,
        )

    def mark_failed(
        self,
        job_id: str,
        *,
        error: str,
        stage: JobStage | str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        return self.update(
            job_id,
            status=JobStatus.FAILED.value,
            stage=str(stage or JobStage.FAILED),
            message="Job failed.",
            error=error,
            finished_at=now,
        )


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
