from __future__ import annotations

from metrics.job_metrics import JobStage
from metrics.store import JobMetricsStore


class ProgressReporter:
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

    def mark_done(self, message: str = "Job done: chunks sent to Elasticsearch.") -> None:
        self.store.mark_done(self.job_id, message=message)

    def mark_failed(
        self,
        error: str,
        stage: JobStage | str | None = None,
    ) -> None:
        self.store.mark_failed(self.job_id, error=error, stage=stage)


class NullProgressReporter:
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
