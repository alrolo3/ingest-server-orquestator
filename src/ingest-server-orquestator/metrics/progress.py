from __future__ import annotations

from metrics.job_metrics import JobStage
from metrics.store import JobMetricsStore


_STAGE_TIMING_FIELDS = {
    "parse": "parse_seconds",
    "chunk": "chunk_seconds",
    "dispatch": "dispatch_seconds",
}


def _seconds(value: float) -> float:
    return round(max(0.0, float(value)), 3)


def _rate(count: object, seconds: object) -> float | None:
    try:
        count_value = int(count or 0)
        seconds_value = float(seconds or 0)
    except (TypeError, ValueError):
        return None
    if count_value <= 0 or seconds_value <= 0:
        return None
    return round(count_value / seconds_value, 3)


class ProgressReporter:
    """Small facade that records parser/chunker/dispatcher progress for one job."""

    def __init__(self, job_id: str, store: JobMetricsStore) -> None:
        self.job_id = job_id
        self.store = store

    def mark_stage(self, stage: JobStage | str, message: str | None = None) -> None:
        self.store.mark_stage(self.job_id, stage, message=message)

    def set_total_pages(self, total_pages: int | None) -> None:
        if total_pages is None:
            self.store.update(self.job_id, total_pages=None)
            return
        self.store.update(self.job_id, total_pages=max(0, int(total_pages)))

    def page_processed(
        self,
        page_no: int | None = None,
        message: str | None = None,
    ) -> None:
        record = self.store.get(self.job_id) or {}
        processed = int(record.get("pages_processed") or 0) + 1
        total_pages = record.get("total_pages")
        if total_pages is not None:
            processed = min(processed, int(total_pages))
        changes: dict[str, object] = {"pages_processed": processed}
        if message is not None:
            changes["message"] = message
        elif page_no is not None:
            changes["message"] = f"Processed page {page_no}."
        self.store.update(self.job_id, **changes)

    def chunks_created(self, count: int) -> None:
        self.store.update(self.job_id, chunks_created=max(0, int(count)))

    def chunks_dispatched(self, count: int) -> None:
        self.store.update(self.job_id, chunks_dispatched=max(0, int(count)))

    def set_output(self, *, file_name: str, path: str, url: str) -> None:
        self.store.update(
            self.job_id,
            output_file_name=file_name,
            output_path=path,
            output_url=url,
        )

    def record_timing(self, name: str, seconds: float) -> None:
        timing_name = str(name).strip().lower()
        if not timing_name:
            return

        elapsed = _seconds(seconds)
        record = self.store.get(self.job_id) or {}
        changes: dict[str, object] = {}

        if timing_name == "total":
            changes["elapsed_seconds"] = elapsed
        else:
            stage_timings = dict(record.get("stage_timings") or {})
            stage_timings[timing_name] = elapsed
            changes["stage_timings"] = stage_timings
            changes["slowest_stage"] = max(
                stage_timings,
                key=lambda stage: stage_timings[stage],
            )
            timing_field = _STAGE_TIMING_FIELDS.get(timing_name)
            if timing_field is not None:
                changes[timing_field] = elapsed

        combined = {**record, **changes}
        pages_per_second = _rate(
            combined.get("total_pages"),
            combined.get("parse_seconds"),
        )
        if pages_per_second is not None:
            changes["pages_per_second"] = pages_per_second

        chunks_per_second = _rate(
            combined.get("chunks_created"),
            combined.get("chunk_seconds"),
        )
        if chunks_per_second is not None:
            changes["chunks_per_second"] = chunks_per_second

        dispatch_chunks_per_second = _rate(
            combined.get("chunks_dispatched"),
            combined.get("dispatch_seconds"),
        )
        if dispatch_chunks_per_second is not None:
            changes["dispatch_chunks_per_second"] = dispatch_chunks_per_second

        self.store.update(self.job_id, **changes)

    def mark_done(self, message: str = "Job done: chunks sent to Elasticsearch.") -> None:
        self.store.mark_done(self.job_id, message=message)

    def mark_failed(
        self,
        error: str,
        stage: JobStage | str | None = None,
    ) -> None:
        self.store.mark_failed(self.job_id, error=error, stage=stage)


class NullProgressReporter:
    """No-op progress sink for call sites that need the reporter interface only."""

    @staticmethod
    def mark_stage(
        _stage: JobStage | str,
        _message: str | None = None,
    ) -> None:
        return None

    @staticmethod
    def set_total_pages(_total_pages: int | None) -> None:
        return None

    @staticmethod
    def page_processed(
        _page_no: int | None = None,
        _message: str | None = None,
    ) -> None:
        return None

    @staticmethod
    def chunks_created(_count: int) -> None:
        return None

    @staticmethod
    def chunks_dispatched(_count: int) -> None:
        return None

    @staticmethod
    def set_output(*, file_name: str, path: str, url: str) -> None:
        return None

    @staticmethod
    def record_timing(_name: str, _seconds: float) -> None:
        return None

    @staticmethod
    def mark_done(
        _message: str = "Job done: chunks sent to Elasticsearch.",
    ) -> None:
        return None

    @staticmethod
    def mark_failed(
        _error: str,
        _stage: JobStage | str | None = None,
    ) -> None:
        return None
