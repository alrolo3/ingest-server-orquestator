import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from docling.datamodel.base_models import InputFormat
from docling_core.types.doc.document import DoclingDocument, TitleItem

from config.config import ServerConfig
from metrics.progress import NullProgressReporter
from processing.parsers.docling_parser import (
    DoclingParser,
    _document_title,
)
from processing.parsers.docling_progress import ProgressReportingStandardPdfPipeline
from queues.domain.job import Job


class DoclingParserTest(unittest.TestCase):
    def test_document_title_uses_docling_title_item(self) -> None:
        doc = DoclingDocument(name="fallback")
        doc.texts.append(
            TitleItem(
                self_ref="#/texts/0",
                orig="Document title",
                text="Document title",
            )
        )

        self.assertEqual("Document title", _document_title(doc))

    def test_document_title_falls_back_to_doc_name(self) -> None:
        doc = DoclingDocument(name="fallback")

        self.assertEqual("fallback", _document_title(doc))

    def test_parse_disables_chart_extraction_enrichment(self) -> None:
        doc = DoclingDocument(name="fallback")
        converter = MagicMock()
        converter.convert.return_value = SimpleNamespace(document=doc)

        with patch(
            "processing.parsers.docling_parser.DocumentConverter",
            return_value=converter,
        ) as document_converter:
            parser = DoclingParser(
                type="docling",
                server_config=ServerConfig(
                    app_name="test",
                    environment="test",
                    inbound_queue_name="inbound",
                    chunk_max_tokens=2048,
                    tokenizer_path=Path("/tmp/tokenizer"),
                ),
            )
            with TemporaryDirectory() as temp_dir:
                source_path = Path(temp_dir) / "uploaded.pdf"
                source_path.write_bytes(b"%PDF-1.4\n")
                job = Job(
                    job_id="job-1",
                    parser_type="docling",
                    input_data={
                        "file_path": str(source_path),
                        "file_name": "uploaded.pdf",
                        "mime_type": "application/pdf",
                    },
                    chunker_type="docling",
                )

                parsed_document = parser.parse(job, NullProgressReporter())

        format_options = document_converter.call_args.kwargs["format_options"]
        pipeline_options = format_options[InputFormat.PDF].pipeline_options

        self.assertFalse(pipeline_options.do_chart_extraction)
        self.assertEqual("cuda:0", pipeline_options.accelerator_options.device)
        self.assertIs(
            ProgressReportingStandardPdfPipeline,
            format_options[InputFormat.PDF].pipeline_cls,
        )
        converter.convert.assert_called_once_with(source_path)
        self.assertEqual("uploaded.pdf", parsed_document.source_file_name)
        self.assertEqual(str(source_path), parsed_document.source_path)
        self.assertEqual("application/pdf", parsed_document.mime_type)


if __name__ == "__main__":
    unittest.main()
