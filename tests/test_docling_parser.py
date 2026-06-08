import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import EasyOcrOptions
from docling_core.types.doc.document import DoclingDocument, TitleItem

from config.config import ServerConfig
from metrics.progress import NullProgressReporter
from processing.parsers.docling_parser import (
    DoclingParser,
    _docling_ocr_options,
    _document_title,
)
from processing.parsers.docling_progress import ProgressReportingStandardPdfPipeline
from processing.parsers.mineru_ocr_model import MinerUOcrOptions
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
                    worker_max_workers=1,
                    chunk_max_tokens=2048,
                    tokenizer_path=Path("/tmp/tokenizer"),
                    docling_artifacts_path=Path("/tmp/docling-artifacts"),
                    docling_pp_layout_model_path=Path("/tmp/pp-doclayout-v3"),
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
        self.assertTrue(pipeline_options.do_ocr)
        self.assertIsInstance(pipeline_options.ocr_options, EasyOcrOptions)
        self.assertEqual(["es", "en"], pipeline_options.ocr_options.lang)
        self.assertEqual(
            "/tmp/docling-artifacts/EasyOcr",
            pipeline_options.ocr_options.model_storage_directory,
        )
        self.assertFalse(pipeline_options.ocr_options.download_enabled)
        self.assertFalse(pipeline_options.ocr_options.use_gpu)
        self.assertEqual(8, pipeline_options.ocr_batch_size)
        self.assertEqual(4, pipeline_options.layout_batch_size)
        self.assertEqual(8, pipeline_options.table_batch_size)
        self.assertEqual(16, pipeline_options.queue_max_size)
        self.assertEqual(4, pipeline_options.layout_options.batch_size)
        self.assertEqual("cuda:0", pipeline_options.accelerator_options.device)
        self.assertIs(
            ProgressReportingStandardPdfPipeline,
            format_options[InputFormat.PDF].pipeline_cls,
        )
        converter.convert.assert_called_once_with(source_path)
        self.assertEqual("uploaded.pdf", parsed_document.source_file_name)
        self.assertEqual(str(source_path), parsed_document.source_path)
        self.assertEqual("application/pdf", parsed_document.mime_type)

    def test_docling_ocr_options_supports_mineru(self) -> None:
        options = _docling_ocr_options(
            ServerConfig(
                app_name="test",
                environment="test",
                inbound_queue_name="inbound",
                worker_max_workers=1,
                chunk_max_tokens=2048,
                tokenizer_path=Path("/tmp/tokenizer"),
                docling_artifacts_path=Path("/tmp/docling-artifacts"),
                docling_pp_layout_model_path=Path("/tmp/pp-doclayout-v3"),
                docling_mineru_model_path=Path("/tmp/mineru"),
                docling_ocr_engine="mineru",
                docling_mineru_device="cpu",
                docling_mineru_dtype="bfloat16",
                docling_mineru_batch_size=2,
                docling_mineru_image_analysis=True,
            )
        )

        self.assertIsInstance(options, MinerUOcrOptions)
        self.assertEqual(["es", "en"], options.lang)
        self.assertEqual("/tmp/mineru", options.model_path)
        self.assertEqual("cpu", options.device)
        self.assertEqual("bfloat16", options.dtype)
        self.assertEqual(2, options.batch_size)
        self.assertTrue(options.image_analysis)


if __name__ == "__main__":
    unittest.main()
