import pickle
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from queues.domain.job import Job
from workers.job_runner import _serializable_job_error, _write_markdown_output, output_file_name


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


if __name__ == "__main__":
    unittest.main()
