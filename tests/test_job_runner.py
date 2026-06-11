import json
import pickle
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from model.document_chunk import DocumentChunk
from queues.domain.job import Job
from workers.job_runner import (
    _serializable_job_error,
    _write_chunk_outputs,
    _write_markdown_output,
    output_file_name,
)


class UnpickleableError(Exception):
    def __reduce__(self):  # pragma: no cover - called by pickle internals
        raise TypeError("cannot pickle")


class JobRunnerTest(unittest.TestCase):
    def test_serializable_job_error_wraps_unpickleable_exception(self) -> None:
        error = _serializable_job_error(UnpickleableError("pipeline failed"))

        pickle.dumps(error)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual("UnpickleableError: pipeline failed", str(error))

    def test_output_file_name_uses_sanitized_document_title(self) -> None:
        job = Job(
            job_id="job-1",
            parser_type="docling",
            input_data={"file_name": "source.pdf"},
            chunker_type="token",
        )
        parsed_document = SimpleNamespace(
            title="Incident/Response: Guide?",
            source_file_name="source.pdf",
        )

        self.assertEqual(
            "Incident Response Guide output.md",
            output_file_name(job, parsed_document),
        )

    def test_output_file_name_falls_back_to_source_file_stem(self) -> None:
        job = Job(
            job_id="job-1",
            parser_type="docling",
            input_data={"file_name": "uploaded.pdf"},
            chunker_type="token",
        )
        parsed_document = SimpleNamespace(title=None, source_file_name="source.pdf")

        self.assertEqual("source output.md", output_file_name(job, parsed_document))

    def test_write_markdown_output_uses_job_directory(self) -> None:
        job = Job(
            job_id="job-1",
            parser_type="docling",
            input_data={"file_name": "source.pdf"},
            chunker_type="token",
        )
        parsed_document = SimpleNamespace(
            title="My Document",
            source_file_name="source.pdf",
            get_markdown=lambda: "# My Document\n",
        )

        with TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            with patch("workers.job_runner.OUTPUT_DIR", output_root):
                output_path = _write_markdown_output(job, parsed_document)

            self.assertEqual(
                output_root / "job-1" / "My Document output.md",
                output_path,
            )
            self.assertEqual("# My Document\n", output_path.read_text(encoding="utf-8"))

    def test_write_chunk_outputs_uses_job_chunks_directory(self) -> None:
        job = Job(
            job_id="job-1",
            parser_type="docling",
            input_data={"file_name": "source.pdf"},
            chunker_type="token",
        )
        chunks = [
            DocumentChunk(
                content="first chunk",
                content_sparse="first chunk",
                document_id="doc-1",
                chunk_id="doc-1/chunk:1",
                chunk_index=0,
                chunking_strategy="token",
                page_number=1,
                source_file_name="source.pdf",
            ),
            DocumentChunk(
                content="second chunk",
                content_sparse="second chunk",
                document_id="doc-1",
                chunk_id="doc-1/chunk:2",
                chunk_index=1,
                chunking_strategy="token",
                source_file_name="source.pdf",
            ),
        ]

        with TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            with patch("workers.job_runner.OUTPUT_DIR", output_root):
                chunks_dir = _write_chunk_outputs(job, chunks)

            self.assertEqual(output_root / "job-1" / "chunks", chunks_dir)
            chunk_files = sorted(path.name for path in chunks_dir.iterdir())
            self.assertEqual(
                [
                    "0001-doc-1 chunk 1.json",
                    "0002-doc-1 chunk 2.json",
                ],
                chunk_files,
            )

            first_chunk = json.loads((chunks_dir / chunk_files[0]).read_text())
            second_chunk = json.loads((chunks_dir / chunk_files[1]).read_text())
            self.assertEqual("first chunk", first_chunk["content"])
            self.assertEqual("doc-1/chunk:1", first_chunk["chunk_id"])
            self.assertEqual(1, first_chunk["page_number"])
            self.assertNotIn("title", first_chunk)
            self.assertEqual("second chunk", second_chunk["content"])
            self.assertNotIn("page_number", second_chunk)

    def test_write_chunk_outputs_creates_empty_chunks_directory(self) -> None:
        job = Job(
            job_id="job-1",
            parser_type="docling",
            input_data={"file_name": "source.pdf"},
            chunker_type="token",
        )

        with TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            with patch("workers.job_runner.OUTPUT_DIR", output_root):
                chunks_dir = _write_chunk_outputs(job, [])

            self.assertEqual(output_root / "job-1" / "chunks", chunks_dir)
            self.assertEqual([], list(chunks_dir.iterdir()))


if __name__ == "__main__":
    unittest.main()
