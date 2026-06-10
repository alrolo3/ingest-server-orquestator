#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "ingest-server-orquestator"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config.config import get_server_config
from metrics.progress import ProgressReporter
from metrics.store import JobMetricsStore
from processing.chunker_factory import ChunkerFactory
from processing.parsers.docling_parser import DoclingParser
from queues.domain.job import Job


def _job_for_path(path: Path, index: int) -> Job:
    return Job(
        job_id=f"benchmark-{index:04d}",
        parser_type="docling",
        input_data={
            "source": "benchmark",
            "file_name": path.name,
            "file_path": str(path),
            "mime_type": "application/pdf",
            "size_bytes": path.stat().st_size,
        },
        chunker_type="token",
    )


def _benchmark_pdf(path: Path, index: int, *, with_chunking: bool) -> dict[str, Any]:
    settings = get_server_config()
    store = JobMetricsStore()
    job = _job_for_path(path, index)
    store.create_for_job(job)
    progress = ProgressReporter(job.job_id, store)

    parser = DoclingParser(type="docling", server_config=settings)
    started_at = perf_counter()
    parse_started_at = perf_counter()
    parsed_document = parser.parse(job, progress)
    progress.record_timing("parse", perf_counter() - parse_started_at)

    if with_chunking:
        chunker = ChunkerFactory.create(
            chunker_backend=job.parser_type,
            chunker_type=job.chunker_type,
            server_config=settings,
            tokenizer_path=settings.tokenizer_path,
        )
        chunk_started_at = perf_counter()
        chunks = chunker.chunk(parsed_document, progress)
        progress.chunks_created(len(chunks))
        progress.record_timing("chunk", perf_counter() - chunk_started_at)

    progress.record_timing("total", perf_counter() - started_at)
    metrics = store.get(job.job_id) or {}
    return {
        "file": str(path),
        "pages": parsed_document.page_count,
        "chunks": metrics.get("chunks_created"),
        "elapsed_seconds": metrics.get("elapsed_seconds"),
        "parse_seconds": metrics.get("parse_seconds"),
        "chunk_seconds": metrics.get("chunk_seconds"),
        "pages_per_second": metrics.get("pages_per_second"),
        "chunks_per_second": metrics.get("chunks_per_second"),
        "slowest_stage": metrics.get("slowest_stage"),
        "stage_timings": metrics.get("stage_timings") or {},
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark Docling parsing without dispatching to Elasticsearch.",
    )
    parser.add_argument(
        "pdfs",
        nargs="+",
        type=Path,
        help="PDF files to benchmark.",
    )
    parser.add_argument(
        "--with-chunking",
        action="store_true",
        help="Also run the configured chunker after parsing.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path. Defaults to stdout.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    missing = [path for path in args.pdfs if not path.is_file()]
    if missing:
        for path in missing:
            print(f"File does not exist: {path}", file=sys.stderr)
        return 2

    results = [
        _benchmark_pdf(path, index, with_chunking=args.with_chunking)
        for index, path in enumerate(args.pdfs, start=1)
    ]
    body = json.dumps({"documents": results}, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.write_text(f"{body}\n", encoding="utf-8")
    else:
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
