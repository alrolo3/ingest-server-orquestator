# queues/workers/job_runner.py
import faulthandler
import signal
import sys
from os import getpid
from pathlib import Path

import torch

from config.config import get_server_config
from processing.chunker_factory import ChunkerFactory
from processing.parseer_factory import ParserFactory
from processing.parsers.docling_parser import DoclingParser
from queues.domain.job import Job


def job_runner(job: Job) -> None:
    torch.set_float32_matmul_precision("high")

    settings = get_server_config()

    parser = ParserFactory.create(
        parser_type=job.parser_type,
        server_config=settings,
    )

    parsed_document = parser.parse(job)

    # 3) CHUNKING STAGE
    chunker = ChunkerFactory.create(
        chunker_backend=job.parser_type,
        chunker_type=job.chunker_type,
        server_config=settings,
        tokenizer_path=settings.tokenizer_path,
    )

    chunks = chunker.chunk(parsed_document)
    #print(chunks)

    # OUTPUT DISPATCH STAGE

    markdown = parsed_document.get_markdown()

    output_path = Path.cwd() / f"red-team-{getpid()}.md"
    output_path.write_text(markdown, encoding="utf-8")




