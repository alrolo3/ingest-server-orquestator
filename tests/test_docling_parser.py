import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import EasyOcrOptions, TableFormerMode
from docling.document_converter import MarkdownFormatOption, SimplePipeline
from docling_core.types.doc.document import DoclingDocument, TitleItem

from config.config import ServerConfig
from metrics.progress import NullProgressReporter
from processing.parsers.docling_parser import (
    DoclingParser,
    _JSON_INPUT_FORMAT,
    _docling_ocr_options,
    _docling_input_format,
    _document_title,
)
from processing.parsers.docling_progress import ProgressReportingStandardPdfPipeline
from processing.parsers.mineru_ocr_model import MinerUOcrOptions
from processing.parsers.surya_ocr_model import SuryaOcrOptions
from queues.domain.job import Job


class DoclingParserTest(unittest.TestCase):
    def test_input_format_detects_markdown_by_mime_type(self) -> None:
        self.assertEqual(
            InputFormat.MD,
            _docling_input_format(Path("uploaded"), "text/markdown; charset=utf-8"),
        )

    def test_input_format_detects_markdown_by_extension(self) -> None:
        self.assertEqual(
            InputFormat.MD,
            _docling_input_format(Path("uploaded.markdown"), "application/octet-stream"),
        )

    def test_input_format_detects_json_by_mime_type(self) -> None:
        self.assertEqual(
            _JSON_INPUT_FORMAT,
            _docling_input_format(Path("uploaded"), "application/activity+json"),
        )

    def test_input_format_detects_json_by_extension(self) -> None:
        self.assertEqual(
            _JSON_INPUT_FORMAT,
            _docling_input_format(Path("uploaded.json"), "application/octet-stream"),
        )

    def test_input_format_rejects_unsupported_files(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported document format"):
            _docling_input_format(Path("uploaded.txt"), "text/plain")

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

    def test_document_title_cleans_uuid_prefixed_doc_name(self) -> None:
        doc = DoclingDocument(
            name="7b6c94b653dc44d3b5bc68c5d080189a-guia-notificacion.pdf"
        )

        self.assertEqual("guia notificacion", _document_title(doc))

    def test_document_title_uses_source_file_fallback(self) -> None:
        doc = DoclingDocument(name="")

        self.assertEqual(
            "guia notificacion",
            _document_title(
                doc,
                source_file_name=(
                    "7b6c94b653dc44d3b5bc68c5d080189a-guia-notificacion.pdf"
                ),
            ),
        )

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
        self.assertEqual(8, pipeline_options.accelerator_options.num_threads)
        self.assertTrue(pipeline_options.do_picture_classification)
        self.assertTrue(pipeline_options.do_picture_description)
        self.assertEqual(2.0, pipeline_options.images_scale)
        self.assertEqual(16, pipeline_options.picture_description_options.concurrency)
        self.assertEqual(240, pipeline_options.picture_description_options.timeout)
        self.assertEqual(
            "Qwen3.5-9B",
            pipeline_options.picture_description_options.params["model"],
        )
        self.assertEqual(
            TableFormerMode.ACCURATE,
            pipeline_options.table_structure_options.mode,
        )
        self.assertFalse(pipeline_options.do_code_enrichment)
        self.assertFalse(pipeline_options.do_formula_enrichment)
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
        self.assertEqual("fallback", parsed_document.title)

    def test_parse_supports_markdown_files(self) -> None:
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
                source_path = Path(temp_dir) / "uploaded.md"
                source_path.write_text("# Uploaded\n\nBody", encoding="utf-8")
                job = Job(
                    job_id="job-1",
                    parser_type="docling",
                    input_data={
                        "file_path": str(source_path),
                        "file_name": "uploaded.md",
                        "mime_type": "text/markdown",
                    },
                    chunker_type="docling",
                )

                parsed_document = parser.parse(job, NullProgressReporter())

        allowed_formats = document_converter.call_args.kwargs["allowed_formats"]
        format_options = document_converter.call_args.kwargs["format_options"]
        markdown_options = format_options[InputFormat.MD]

        self.assertEqual([InputFormat.PDF, InputFormat.MD], allowed_formats)
        self.assertIsInstance(markdown_options, MarkdownFormatOption)
        self.assertIs(SimplePipeline, markdown_options.pipeline_cls)
        self.assertIsNone(markdown_options.pipeline_options.artifacts_path)
        self.assertFalse(markdown_options.pipeline_options.enable_remote_services)
        self.assertFalse(markdown_options.pipeline_options.allow_external_plugins)
        self.assertFalse(markdown_options.backend_options.enable_remote_fetch)
        self.assertFalse(markdown_options.backend_options.enable_local_fetch)
        self.assertFalse(markdown_options.backend_options.fetch_images)
        converter.convert.assert_called_once_with(source_path)
        self.assertEqual("uploaded.md", parsed_document.source_file_name)
        self.assertEqual(str(source_path), parsed_document.source_path)
        self.assertEqual("text/markdown", parsed_document.mime_type)
        self.assertEqual("fallback", parsed_document.title)

    def test_parse_preprocesses_arbitrary_json_as_markdown(self) -> None:
        doc = DoclingDocument(name="uploaded")
        converter = MagicMock()
        converter.convert_string.return_value = SimpleNamespace(document=doc)

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
                source_path = Path(temp_dir) / "uploaded.json"
                source_path.write_text(
                    '{"users": [{"id": 1, "name": "A"}]}',
                    encoding="utf-8",
                )
                job = Job(
                    job_id="job-1",
                    parser_type="docling",
                    input_data={
                        "file_path": str(source_path),
                        "file_name": "uploaded.json",
                        "mime_type": "application/json",
                    },
                    chunker_type="docling",
                )

                parsed_document = parser.parse(job, NullProgressReporter())

        allowed_formats = document_converter.call_args.kwargs["allowed_formats"]
        self.assertEqual([InputFormat.PDF, InputFormat.MD], allowed_formats)
        converter.convert.assert_not_called()
        converter.convert_string.assert_called_once()
        markdown, = converter.convert_string.call_args.args
        self.assertIn("# uploaded", markdown)
        self.assertIn("| id | name |", markdown)
        self.assertEqual(InputFormat.MD, converter.convert_string.call_args.kwargs["format"])
        self.assertEqual("uploaded", converter.convert_string.call_args.kwargs["name"])
        self.assertEqual("uploaded.json", parsed_document.source_file_name)
        self.assertEqual(str(source_path), parsed_document.source_path)
        self.assertEqual("application/json", parsed_document.mime_type)
        self.assertEqual(
            {
                "docling": {
                    "parser": "docling",
                    "input_format": "json",
                    "preprocessed_format": "md",
                }
            },
            parsed_document.metadata,
        )

    def test_parse_uses_configurable_performance_options(self) -> None:
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
                    docling_accelerator_threads=3,
                    docling_picture_description_enabled=False,
                    docling_picture_classification_enabled=False,
                    docling_picture_description_concurrency=2,
                    docling_picture_description_timeout=30,
                    docling_picture_description_model="custom-vlm",
                    docling_images_scale=1.5,
                    docling_table_mode="fast",
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

                parser.parse(job, NullProgressReporter())

        format_options = document_converter.call_args.kwargs["format_options"]
        pipeline_options = format_options[InputFormat.PDF].pipeline_options

        self.assertEqual(3, pipeline_options.accelerator_options.num_threads)
        self.assertFalse(pipeline_options.do_picture_classification)
        self.assertFalse(pipeline_options.do_picture_description)
        self.assertEqual(1.5, pipeline_options.images_scale)
        self.assertEqual(2, pipeline_options.picture_description_options.concurrency)
        self.assertEqual(30, pipeline_options.picture_description_options.timeout)
        self.assertEqual(
            "custom-vlm",
            pipeline_options.picture_description_options.params["model"],
        )
        self.assertEqual(TableFormerMode.FAST, pipeline_options.table_structure_options.mode)

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

    def test_docling_ocr_options_supports_surya(self) -> None:
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
                docling_ocr_engine="surya",
                docling_surya_scale=3.0,
                docling_surya_confidence=0.75,
                docling_surya_inference_url="http://surya:8000/v1",
                docling_surya_inference_backend="vllm",
                docling_surya_inference_parallel=4,
                docling_surya_keep_alive=False,
            )
        )

        self.assertIsInstance(options, SuryaOcrOptions)
        self.assertEqual(["es", "en"], options.lang)
        self.assertEqual(3.0, options.scale)
        self.assertEqual(0.75, options.confidence)
        self.assertEqual("http://surya:8000/v1", options.inference_url)
        self.assertEqual("vllm", options.inference_backend)
        self.assertEqual(4, options.inference_parallel)
        self.assertFalse(options.keep_alive)

    def test_docling_ocr_options_error_mentions_surya(self) -> None:
        with self.assertRaisesRegex(ValueError, "surya"):
            _docling_ocr_options(
                ServerConfig(
                    app_name="test",
                    environment="test",
                    inbound_queue_name="inbound",
                    worker_max_workers=1,
                    chunk_max_tokens=2048,
                    tokenizer_path=Path("/tmp/tokenizer"),
                    docling_artifacts_path=Path("/tmp/docling-artifacts"),
                    docling_pp_layout_model_path=Path("/tmp/pp-doclayout-v3"),
                    docling_ocr_engine="unknown",
                )
            )


if __name__ == "__main__":
    unittest.main()
