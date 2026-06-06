# queues/workers/job_runner.py
from config.gpu import configure_gpu_environment, configure_torch_cuda_device

# Must run before importing torch or parser modules that can load CUDA libraries.
configure_gpu_environment()

from os import getpid
from pathlib import Path

import torch

from config.config import get_server_config
from dispatcher.elastic.elastic import ElasticsearchDispatch
from metrics.job_metrics import JobStage
from metrics.progress import ProgressReporter
from metrics.store import JobMetricsStore
from processing.chunker_factory import ChunkerFactory
from processing.parseer_factory import ParserFactory
from queues.domain.job import Job


def job_runner(job: Job, metrics_store: JobMetricsStore | None = None) -> None:
    settings = get_server_config()
    metrics = metrics_store or JobMetricsStore()
    metrics.ensure_job(job)
    progress = ProgressReporter(job.job_id, metrics)
    current_stage = JobStage.RUNNING

    try:
        configure_torch_cuda_device(torch, settings)
        torch.set_float32_matmul_precision("high")
        progress.mark_stage(JobStage.RUNNING, "Worker started processing.")

        parser = ParserFactory.create(
            parser_type=job.parser_type,
            server_config=settings,
        )

        current_stage = JobStage.PARSING
        progress.mark_stage(current_stage, "Parsing document.")
        parsed_document = parser.parse(job, progress)

        current_stage = JobStage.CHUNKING
        progress.mark_stage(current_stage, "Creating chunks.")
        chunker = ChunkerFactory.create(
            chunker_backend=job.parser_type,
            chunker_type=job.chunker_type,
            server_config=settings,
            tokenizer_path=settings.tokenizer_path,
        )

        chunks = chunker.chunk(parsed_document, progress)
        progress.chunks_created(len(chunks))
        #print(chunks)

        current_stage = JobStage.DISPATCHING
        progress.mark_stage(current_stage, "Sending chunks to Elasticsearch.")
        dispatcher = ElasticsearchDispatch(server_config=settings)
        dispatcher.dispatch_chunks(chunks)
        progress.chunks_dispatched(len(chunks))
        progress.mark_done("Job done: chunks sent to Elasticsearch.")
    except Exception as exc:
        progress.mark_failed(str(exc), stage=current_stage)
        raise

    try:
        markdown = parsed_document.get_markdown()
        output_path = Path.cwd() / f"red-team-{getpid()}.md"
        output_path.write_text(markdown, encoding="utf-8")
    except Exception as exc:
        print(f"Failed to write markdown output: {exc}", flush=True)
