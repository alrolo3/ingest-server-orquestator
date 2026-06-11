# queues/workers/job_runner.py
from config.gpu import configure_gpu_environment, configure_torch_cuda_device

# Must run before importing torch or parser modules that can load CUDA libraries.
configure_gpu_environment()

import logging
from os import getenv
from pathlib import Path
import re
from time import perf_counter
from typing import Any

import torch

from config.config import get_server_config
from config.paths import OUTPUT_DIR
from dispatcher.elastic.elastic import ElasticsearchDispatch
from metrics.job_metrics import JobStage
from metrics.progress import ProgressReporter
from metrics.store import JobMetricsStore
from processing.chunker_factory import ChunkerFactory
from processing.parseer_factory import ParserFactory
from queues.domain.job import Job


logging.basicConfig(
    level=getenv("INGEST_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    force=True,
)
LOGGER = logging.getLogger("ingest-server-orquestator.job-runner")

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_WHITESPACE = re.compile(r"\s+")
_MAX_OUTPUT_TITLE_LENGTH = 120


def _sanitize_output_title(value: object) -> str:
    title = str(value or "").strip()
    title = _INVALID_FILENAME_CHARS.sub(" ", title)
    title = _WHITESPACE.sub(" ", title).strip(" .")
    if not title:
        return "document"
    return title[:_MAX_OUTPUT_TITLE_LENGTH].rstrip(" .") or "document"


def _source_title(job: Job, parsed_document: Any) -> str:
    for value in (
        getattr(parsed_document, "title", None),
        getattr(parsed_document, "source_file_name", None),
        job.input_data.get("file_name"),
        job.job_id,
    ):
        if not value:
            continue
        if value != getattr(parsed_document, "title", None):
            stem = Path(str(value).replace("\\", "/")).stem
            if stem:
                return stem
        return str(value)
    return "document"


def output_file_name(job: Job, parsed_document: Any) -> str:
    title = _sanitize_output_title(_source_title(job, parsed_document))
    return f"{title} output.md"


def _output_url(job_id: str) -> str:
    return f"/api/v1/ingest/jobs/{job_id}/output"


def _write_markdown_output(job: Job, parsed_document: Any) -> Path:
    markdown = parsed_document.get_markdown()
    output_dir = OUTPUT_DIR / _sanitize_output_title(job.job_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / output_file_name(job, parsed_document)
    path.write_text(markdown, encoding="utf-8")
    return path


def _serializable_job_error(exc: Exception) -> RuntimeError:
    return RuntimeError(f"{type(exc).__name__}: {exc}")


def job_runner(job: Job, metrics_store: JobMetricsStore | None = None) -> None:
    job_started_at = perf_counter()
    settings = get_server_config()
    metrics = metrics_store or JobMetricsStore()
    metrics.ensure_job(job)
    progress = ProgressReporter(job.job_id, metrics)
    current_stage = JobStage.RUNNING

    try:
        configure_torch_cuda_device(torch, settings)
        torch.set_float32_matmul_precision("high")
        progress.mark_stage(JobStage.RUNNING, "Worker started processing.")
        LOGGER.info(
            "Started job job_id=%s parser=%s chunker=%s input=%s",
            job.job_id,
            job.parser_type,
            job.chunker_type,
            job.input_data,
        )

        parser = ParserFactory.create(
            parser_type=job.parser_type,
            server_config=settings,
        )

        current_stage = JobStage.PARSING
        progress.mark_stage(current_stage, "Parsing document.")
        LOGGER.info("Parsing job job_id=%s", job.job_id)
        stage_started_at = perf_counter()
        parsed_document = parser.parse(job, progress)
        progress.record_timing("parse", perf_counter() - stage_started_at)

        current_stage = JobStage.CHUNKING
        progress.mark_stage(current_stage, "Creating chunks.")
        LOGGER.info("Chunking job job_id=%s", job.job_id)
        chunker = ChunkerFactory.create(
            chunker_backend=job.parser_type,
            chunker_type=job.chunker_type,
            server_config=settings,
            tokenizer_path=settings.tokenizer_path,
        )

        stage_started_at = perf_counter()
        chunks = chunker.chunk(parsed_document, progress)
        progress.chunks_created(len(chunks))
        progress.record_timing("chunk", perf_counter() - stage_started_at)
        LOGGER.info("Created chunks job_id=%s count=%s", job.job_id, len(chunks))

        current_stage = JobStage.DISPATCHING
        progress.mark_stage(current_stage, "Sending chunks to Elasticsearch.")
        LOGGER.info("Dispatching chunks job_id=%s count=%s", job.job_id, len(chunks))
        dispatcher = ElasticsearchDispatch(server_config=settings)
        stage_started_at = perf_counter()
        dispatcher.dispatch_chunks(chunks)
        progress.chunks_dispatched(len(chunks))
        progress.record_timing("dispatch", perf_counter() - stage_started_at)

        current_stage = JobStage.OUTPUTTING
        progress.mark_stage(current_stage, "Writing markdown output.")
        output_path = _write_markdown_output(job, parsed_document)
        progress.set_output(
            file_name=output_path.name,
            path=str(output_path),
            url=_output_url(job.job_id),
        )
        progress.record_timing("total", perf_counter() - job_started_at)
        progress.mark_done("Job done: chunks sent to Elasticsearch.")
        LOGGER.info("Wrote markdown output job_id=%s output_path=%s", job.job_id, output_path)
        LOGGER.info("Finished job job_id=%s", job.job_id)
    except Exception as exc:
        serializable_error = _serializable_job_error(exc)
        progress.record_timing("total", perf_counter() - job_started_at)
        progress.mark_failed(str(serializable_error), stage=current_stage)
        LOGGER.exception("Job failed job_id=%s stage=%s", job.job_id, current_stage)
        raise serializable_error from None
