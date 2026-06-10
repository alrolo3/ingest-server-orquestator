# queues/workers/job_runner.py
from config.gpu import configure_gpu_environment, configure_torch_cuda_device

# Must run before importing torch or parser modules that can load CUDA libraries.
configure_gpu_environment()

import logging
from os import getpid
from os import getenv
from time import perf_counter

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
        progress.record_timing("total", perf_counter() - job_started_at)
        progress.mark_done("Job done: chunks sent to Elasticsearch.")
        LOGGER.info("Finished job job_id=%s", job.job_id)
    except Exception as exc:
        serializable_error = _serializable_job_error(exc)
        progress.record_timing("total", perf_counter() - job_started_at)
        progress.mark_failed(str(serializable_error), stage=current_stage)
        LOGGER.exception("Job failed job_id=%s stage=%s", job.job_id, current_stage)
        raise serializable_error from None

    try:
        markdown = parsed_document.get_markdown()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / f"red-team-{job.job_id}-{getpid()}.md"
        output_path.write_text(markdown, encoding="utf-8")
        LOGGER.info("Wrote markdown output job_id=%s output_path=%s", job.job_id, output_path)
    except Exception as exc:
        LOGGER.exception("Failed to write markdown output job_id=%s", job.job_id)
