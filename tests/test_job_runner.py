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

from config.config import ServerConfig
from model.document_chunk import DocumentChunk
from metrics.store import JobMetricsStore
from queues.domain.job import Job
from workers.job_runner import (
    _serializable_job_error,
    _write_chunk_outputs,
    _write_markdown_output,
    job_runner,
    output_file_name,
)


def _server_config(shared_ingest_dir: Path) -> ServerConfig:
    return ServerConfig(
        app_name="test",
        environment="test",
        inbound_queue_name="queue",
        worker_max_workers=1,
        chunk_max_tokens=8192,
        tokenizer_path=Path("/tmp/tokenizer"),
        docling_artifacts_path=Path("/tmp/docling-artifacts"),
        docling_pp_layout_model_path=Path("/tmp/pp-doclayout-v3"),
        elastic_index_name="open-rag-embeddings-v4",
        elastic_hosts=[],
        shared_ingest_dir=shared_ingest_dir,
        shared_ingest_enabled=True,
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

    def test_job_runner_writes_outputs_before_dispatch_failure(self) -> None:
        job = Job(
            job_id="job-1",
            parser_type="docling",
            input_data={"file_name": "source.pdf", "source": "test"},
            chunker_type="token",
        )
        parsed_document = SimpleNamespace(
            title="My Document",
            source_file_name="source.pdf",
            get_markdown=lambda: "# My Document\n",
        )
        chunks = [
            DocumentChunk(
                content="first chunk",
                content_sparse="first chunk",
                document_id="doc-1",
                chunk_id="chunk-1",
                chunk_index=0,
                chunking_strategy="token",
                source_file_name="source.pdf",
            )
        ]

        class FakeParser:
            @staticmethod
            def parse(_job, _progress):
                return parsed_document

        class FakeChunker:
            @staticmethod
            def chunk(_parsed_document, _progress):
                return chunks

        class FailingDispatch:
            def __init__(self, server_config):
                self.server_config = server_config

            @staticmethod
            def dispatch_chunks(_chunks):
                raise ConnectionError("elastic unavailable")

        metrics = JobMetricsStore()
        with TemporaryDirectory() as temp_dir:
            shared_root = Path(temp_dir)
            settings = _server_config(shared_root)
            with (
                patch("workers.job_runner.get_server_config", return_value=settings),
                patch("workers.job_runner.configure_torch_cuda_device"),
                patch("workers.job_runner.torch.set_float32_matmul_precision"),
                patch("workers.job_runner.DoclingParser", return_value=FakeParser()),
                patch("workers.job_runner.DoclingChunker", return_value=FakeChunker()),
                patch("workers.job_runner.ElasticsearchDispatch", FailingDispatch),
                patch("workers.job_runner.LOGGER.info"),
                patch("workers.job_runner.LOGGER.exception"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "ConnectionError: elastic unavailable",
                ):
                    job_runner(job, metrics)

            output_path = (
                shared_root
                / "embeddings-v4"
                / "output"
                / "job-1"
                / "My Document output.md"
            )
            chunks_dir = output_path.parent / "chunks"
            chunk_path = chunks_dir / "0001-chunk-1.json"
            self.assertEqual("# My Document\n", output_path.read_text(encoding="utf-8"))
            chunk_output = json.loads(chunk_path.read_text(encoding="utf-8"))
            self.assertEqual("first chunk", chunk_output["content"])

        record = metrics.get(job.job_id)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual("failed", record["status"])
        self.assertEqual("dispatching", record["stage"])
        self.assertEqual(str(output_path), record["output_path"])
        self.assertEqual("My Document output.md", record["output_file_name"])
        self.assertEqual(1, record["chunks_created"])
        self.assertEqual(0, record["chunks_dispatched"])

    def test_job_runner_passes_elasticsearch_index_override(self) -> None:
        job = Job(
            job_id="job-1",
            parser_type="docling",
            input_data={"file_name": "case.md", "source": "test"},
            chunker_type="token",
            settings={"elastic_index_name": "case-rag"},
        )
        parsed_document = SimpleNamespace(
            title="Case",
            source_file_name="case.md",
            get_markdown=lambda: "# Case\n",
        )
        chunks = [
            DocumentChunk(
                content="case chunk",
                content_sparse="case chunk",
                document_id="doc-1",
                chunk_id="chunk-1",
                chunk_index=0,
                chunking_strategy="token",
                source_file_name="case.md",
            )
        ]
        created = []

        class FakeParser:
            @staticmethod
            def parse(_job, _progress):
                return parsed_document

        class FakeChunker:
            @staticmethod
            def chunk(_parsed_document, _progress):
                return chunks

        class CapturingDispatch:
            def __init__(self, server_config, **kwargs):
                self.server_config = server_config
                self.kwargs = kwargs
                created.append(self)

            @staticmethod
            def dispatch_chunks(_chunks):
                return None

        metrics = JobMetricsStore()
        with TemporaryDirectory() as temp_dir:
            settings = _server_config(Path(temp_dir))
            with (
                patch("workers.job_runner.get_server_config", return_value=settings),
                patch("workers.job_runner.configure_torch_cuda_device"),
                patch("workers.job_runner.torch.set_float32_matmul_precision"),
                patch("workers.job_runner.DoclingParser", return_value=FakeParser()),
                patch("workers.job_runner.DoclingChunker", return_value=FakeChunker()),
                patch("workers.job_runner.ElasticsearchDispatch", CapturingDispatch),
                patch("workers.job_runner.LOGGER.info"),
            ):
                job_runner(job, metrics)

        self.assertEqual(1, len(created))
        self.assertEqual({"index_name": "case-rag"}, created[0].kwargs)
        record = metrics.get(job.job_id)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual("done", record["status"])
        self.assertEqual(1, record["chunks_dispatched"])


if __name__ == "__main__":
    unittest.main()
