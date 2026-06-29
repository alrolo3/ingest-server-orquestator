from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import logging
from pathlib import Path
from typing import Any

from docling.models.factories import get_ocr_factory
from docling.pipeline import standard_pdf_pipeline as std_pdf
from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline

from metrics.job_metrics import JobStage
from metrics.progress import ProgressReporter
from processing.parsers.mineru_ocr_model import MinerU, MinerUOcrOptions
from processing.parsers.surya_ocr_model import SuryaOcrModel, SuryaOcrOptions


_CURRENT_PROGRESS: ContextVar[ProgressReporter | None] = ContextVar(
    "docling_current_progress",
    default=None,
)
_LOGGER = logging.getLogger(__name__)
_PRODUCER_EXCEPTIONS = (
    AttributeError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


def _input_backend(conv_res: std_pdf.ConversionResult) -> std_pdf.PdfDocumentBackend:
    backend = getattr(conv_res.input, "_backend", None)
    if not isinstance(backend, std_pdf.PdfDocumentBackend):
        raise TypeError("Docling conversion input does not have a PDF backend")
    return backend


def _set_page_backend(page_item: std_pdf.Page, page_backend: Any) -> None:
    setattr(page_item, "_backend", page_backend)


@contextmanager
def docling_progress(progress: ProgressReporter) -> Iterator[None]:
    token = _CURRENT_PROGRESS.set(progress)
    try:
        yield
    finally:
        _CURRENT_PROGRESS.reset(token)


class ProgressReportingStandardPdfPipeline(StandardPdfPipeline):
    """Docling pipeline that reports page progress through the generic reporter."""

    def _make_ocr_model(self, art_path: Path | None) -> object:
        """Select the configured OCR adapter before Docling builds the pipeline."""
        options = self.pipeline_options.ocr_options
        if isinstance(options, MinerUOcrOptions):
            return MinerU(
                options=options,
                enabled=self.pipeline_options.do_ocr,
                artifacts_path=art_path,
                accelerator_options=self.pipeline_options.accelerator_options,
            )

        if isinstance(options, SuryaOcrOptions):
            return SuryaOcrModel(
                options=options,
                enabled=self.pipeline_options.do_ocr,
                artifacts_path=art_path,
                accelerator_options=self.pipeline_options.accelerator_options,
            )

        factory = get_ocr_factory(
            allow_external_plugins=self.pipeline_options.allow_external_plugins,
        )
        return factory.create_instance(
            options=options,
            enabled=self.pipeline_options.do_ocr,
            artifacts_path=art_path,
            accelerator_options=self.pipeline_options.accelerator_options,
        )

    def _build_document(
        self,
        conv_res: std_pdf.ConversionResult,
    ) -> std_pdf.ConversionResult:
        """Mirror Docling's threaded build loop while reporting each completed page."""
        self._page_sizes_by_no = {}
        run_id = next(self._run_seq)
        backend = _input_backend(conv_res)
        progress = _CURRENT_PROGRESS.get()

        expected_page_nos = self._get_expected_page_nos(conv_res)
        if not expected_page_nos:
            conv_res.status = std_pdf.ConversionStatus.FAILURE
            if progress is not None:
                progress.set_total_pages(0)
            return conv_res

        page_by_no: dict[int, std_pdf.Page] = {}
        for expected_page_no in expected_page_nos:
            doc_page = std_pdf.Page(page_no=expected_page_no)
            conv_res.pages.append(doc_page)
            page_by_no[expected_page_no] = doc_page

        total_pages: int = len(expected_page_nos)
        if progress is not None:
            progress.set_total_pages(total_pages)
            progress.mark_stage(
                JobStage.PARSING,
                f"Parsing {total_pages} page(s).",
            )

        ctx: std_pdf.RunContext = self._create_run_ctx()
        for st in ctx.stages:
            st.start()

        proc = std_pdf.ProcessingResult(total_expected=total_pages)
        batch_size: int = 32
        start_time = std_pdf.time.monotonic()
        timeout_exceeded = False
        producer_error: list[Exception] = []

        def _completed_page_nos() -> set[int]:
            failed_page_nos = {
                failed_page_no
                for failed_page_no, _ in proc.failed_pages
                if failed_page_no > 0
            }
            return {processed_page.page_no for processed_page in proc.pages} | failed_page_nos

        def _report_page(
            *,
            reported_page_no: int,
            page_error: Exception | None = None,
        ) -> None:
            if progress is None:
                return
            if page_error is None:
                progress.page_processed(reported_page_no)
                return
            progress.page_processed(
                reported_page_no,
                message=f"Page {reported_page_no} failed during parsing: {page_error}",
            )

        def _produce_pages() -> None:
            try:
                for page_backend in self._iter_requested_page_backends(
                    backend,
                    expected_page_nos,
                ):
                    doc_page = page_by_no.get(page_backend.page_no)
                    if doc_page is None:
                        continue
                    _set_page_backend(doc_page, page_backend)
                    try:
                        doc_page.size = page_backend.get_size()
                        self._page_sizes_by_no[doc_page.page_no] = doc_page.size
                    except _PRODUCER_EXCEPTIONS:
                        if page_backend.is_valid():
                            raise
                    if not ctx.first_stage.input_queue.put(
                        std_pdf.ThreadedItem(
                            payload=doc_page,
                            run_id=run_id,
                            page_no=doc_page.page_no,
                            conv_res=conv_res,
                        )
                    ):
                        break
            except _PRODUCER_EXCEPTIONS as exc:
                producer_error.append(exc)
                _LOGGER.error(
                    "Producer failed for run %d: %s",
                    run_id,
                    exc,
                    exc_info=True,
                )
            finally:
                ctx.first_stage.input_queue.close()

        producer_thread = std_pdf.threading.Thread(
            target=_produce_pages,
            name=f"PageProducer-{run_id}",
            daemon=False,
        )
        producer_thread.start()

        try:
            while proc.success_count + proc.failure_count < total_pages:
                if (
                    self.pipeline_options.document_timeout is not None
                    and not timeout_exceeded
                ):
                    elapsed_time = std_pdf.time.monotonic() - start_time
                    if elapsed_time > self.pipeline_options.document_timeout:
                        _LOGGER.warning(
                            "Document processing time (%.3fs) exceeded timeout of %.3fs",
                            elapsed_time,
                            self.pipeline_options.document_timeout,
                        )
                        timeout_exceeded = True
                        ctx.timed_out_run_ids.add(run_id)
                        ctx.first_stage.input_queue.close()
                        break

                out_batch = ctx.output_queue.get_batch(batch_size, timeout=0.05)
                for itm in out_batch:
                    if itm.run_id != run_id:
                        continue
                    if itm.is_failed or itm.error:
                        item_error = itm.error or RuntimeError("unknown error")
                        proc.failed_pages.append((itm.page_no, item_error))
                        _report_page(
                            reported_page_no=itm.page_no,
                            page_error=item_error,
                        )
                    else:
                        assert itm.payload is not None
                        proc.pages.append(itm.payload)
                        _report_page(reported_page_no=itm.page_no)

                if not out_batch and ctx.output_queue.closed:
                    missing_page_nos = sorted(
                        set(expected_page_nos) - _completed_page_nos()
                    )
                    if missing_page_nos:
                        missing_error = (
                            producer_error[0]
                            if producer_error
                            else RuntimeError("pipeline terminated early")
                        )
                        proc.failed_pages.extend(
                            [
                                (missing_page_no, missing_error)
                                for missing_page_no in missing_page_nos
                            ]
                        )
                        for missing_page_no in missing_page_nos:
                            _report_page(
                                reported_page_no=missing_page_no,
                                page_error=missing_error,
                            )
                    break

            if timeout_exceeded:
                missing_page_nos = sorted(
                    set(expected_page_nos) - _completed_page_nos()
                )
                timeout_error = RuntimeError("document timeout exceeded")
                proc.failed_pages.extend(
                    [
                        (missing_page_no, timeout_error)
                        for missing_page_no in missing_page_nos
                    ]
                )
                for missing_page_no in missing_page_nos:
                    _report_page(
                        reported_page_no=missing_page_no,
                        page_error=timeout_error,
                    )
        finally:
            for st in ctx.stages:
                st.stop()
            ctx.output_queue.close()
            producer_thread.join(timeout=15.0)
            if producer_thread.is_alive():
                _LOGGER.warning(
                    "Producer thread for run %d did not terminate within 15s and will be abandoned.",
                    run_id,
                )

        self._integrate_results(conv_res, proc, timeout_exceeded=timeout_exceeded)
        return conv_res
