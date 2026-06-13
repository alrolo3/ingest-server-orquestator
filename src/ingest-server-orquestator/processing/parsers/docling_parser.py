from pathlib import Path

from config.gpu import configure_gpu_environment

# Must run before importing Docling, EasyOCR, or other CUDA-backed dependencies.
configure_gpu_environment()

from docling.backend.docling_parse_backend import DoclingParseDocumentBackend
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.backend_options import PdfBackendOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.chart_extraction_options import ChartExtractionModelOptions
from docling.datamodel import settings as docling_settings
from docling.datamodel.pipeline_options import (
    CodeFormulaVlmOptions,
    ConvertPipelineOptions,
    EasyOcrOptions,
    OcrAutoOptions,
    PictureDescriptionApiOptions,
    RapidOcrOptions,
    TableFormerMode,
    TableStructureOptions,
    ThreadedPdfPipelineOptions,
)
from docling.document_converter import (
    DocumentConverter,
    MarkdownBackendOptions,
    MarkdownFormatOption,
    PdfFormatOption,
)
from docling_core.types.doc.document import DocItemLabel, DoclingDocument
from docling_pp_doc_layout.options import PPDocLayoutV3Options
from pydantic import AnyUrl

from config.config import ServerConfig
from metrics.progress import ProgressReporter
from model.base_document import DoclingOutputDocument
from model.parsed_document import ParsedDocument
from model.title_normalization import normalize_document_title
from processing.base_parser import AbstractParser
from processing.parsers.docling_progress import (
    ProgressReportingStandardPdfPipeline,
    docling_progress,
)
from processing.parsers.json_markdown import JsonToMarkdownPreprocessor
from processing.parsers.mineru_ocr_model import MinerUOcrOptions
from processing.parsers.surya_ocr_model import SuryaOcrOptions
from queues.domain.job import Job


_JSON_INPUT_FORMAT = "json"
_PDF_MIME_TYPES = {"application/pdf"}
_PDF_SUFFIXES = {".pdf"}
_JSON_MIME_TYPES = {"application/json", "text/json"}
_JSON_SUFFIXES = {".json"}
_MARKDOWN_MIME_TYPES = {"text/markdown", "text/x-markdown"}
_MARKDOWN_SUFFIXES = {".md", ".markdown"}


def _normalized_mime_type(mime_type: str | None) -> str:
    return str(mime_type or "").split(";", 1)[0].strip().lower()


def _is_json_mime_type(mime_type: str) -> bool:
    return mime_type in _JSON_MIME_TYPES or mime_type.endswith("+json")


def _docling_input_format(source_path: Path, mime_type: str | None) -> InputFormat | str:
    suffix = source_path.suffix.lower()
    normalized_mime_type = _normalized_mime_type(mime_type)

    if suffix in _JSON_SUFFIXES or _is_json_mime_type(normalized_mime_type):
        return _JSON_INPUT_FORMAT
    if suffix in _MARKDOWN_SUFFIXES or normalized_mime_type in _MARKDOWN_MIME_TYPES:
        return InputFormat.MD
    if suffix in _PDF_SUFFIXES or normalized_mime_type in _PDF_MIME_TYPES:
        return InputFormat.PDF

    raise ValueError(
        "Unsupported document format for Docling parser: "
        f"path={source_path.name} mime_type={mime_type or 'unknown'}"
    )


def _input_format_value(input_format: InputFormat | str) -> str:
    if isinstance(input_format, InputFormat):
        return input_format.value
    return input_format


def _default_mime_type(input_format: InputFormat | str) -> str:
    if input_format == _JSON_INPUT_FORMAT:
        return "application/json"
    if input_format == InputFormat.MD:
        return "text/markdown"
    return "application/pdf"


def _document_title(
    doc: DoclingDocument,
    source_file_name: str | None = None,
) -> str | None:
    for text_item in doc.texts:
        if text_item.label == DocItemLabel.TITLE:
            title = normalize_document_title(text_item.text)
            if title:
                return title

    return normalize_document_title(
        doc.name,
        strip_extension=True,
    ) or normalize_document_title(
        source_file_name,
        strip_extension=True,
    )


def _job_source_path(job: Job) -> Path:
    file_path = job.input_data.get("file_path")
    if not file_path:
        raise ValueError("Job input_data must include file_path")

    source_path = Path(str(file_path))
    if not source_path.is_file():
        raise FileNotFoundError(f"Job file does not exist: {source_path}")

    return source_path


_RAPID_OCR_LANG_ALIASES = {
    "en": "english",
    "eng": "english",
    "english": "english",
    "zh": "chinese",
    "chi": "chinese",
    "cn": "chinese",
    "chinese": "chinese",
}


def _rapid_ocr_langs(langs: list[str]) -> list[str]:
    normalized_langs: list[str] = []
    unsupported_langs: list[str] = []

    for lang in langs:
        normalized = _RAPID_OCR_LANG_ALIASES.get(lang.strip().lower())
        if normalized is None:
            unsupported_langs.append(lang)
            continue
        normalized_langs.append(normalized)

    if unsupported_langs:
        raise ValueError(
            "RapidOCR supports only english/chinese in this Docling version; "
            f"unsupported configured language(s): {', '.join(unsupported_langs)}"
        )

    return list(dict.fromkeys(normalized_langs)) or ["english"]


def _docling_ocr_options(
    config_server: ServerConfig,
) -> (
    OcrAutoOptions
    | EasyOcrOptions
    | RapidOcrOptions
    | MinerUOcrOptions
    | SuryaOcrOptions
):
    common_options = {
        "lang": config_server.docling_ocr_langs,
        "force_full_page_ocr": config_server.docling_force_full_page_ocr,
        "bitmap_area_threshold": config_server.docling_ocr_bitmap_area_threshold,
    }
    engine = config_server.docling_ocr_engine.strip().lower()

    if engine == "auto":
        return OcrAutoOptions(**common_options)

    if engine == "easyocr":
        return EasyOcrOptions(
            **common_options,
            model_storage_directory=str(config_server.docling_artifacts_path / "EasyOcr"),
            download_enabled=False,
            use_gpu=False,
        )

    if engine == "mineru":
        return MinerUOcrOptions(
            **common_options,
            model_path=str(config_server.docling_mineru_model_path),
            device=config_server.docling_mineru_device,
            dtype=config_server.docling_mineru_dtype,
            batch_size=config_server.docling_mineru_batch_size,
            image_analysis=config_server.docling_mineru_image_analysis,
        )

    if engine == "surya":
        return SuryaOcrOptions(
            **common_options,
            scale=config_server.docling_surya_scale,
            confidence=config_server.docling_surya_confidence,
            inference_url=config_server.docling_surya_inference_url,
            inference_backend=config_server.docling_surya_inference_backend,
            inference_parallel=config_server.docling_surya_inference_parallel,
            keep_alive=config_server.docling_surya_keep_alive,
        )

    if engine == "rapidocr":
        rapid_options = dict(common_options)
        rapid_options["lang"] = _rapid_ocr_langs(config_server.docling_ocr_langs)
        return RapidOcrOptions(
            **rapid_options,
        )

    raise ValueError(
        "Unsupported DOCLING_OCR_ENGINE value: "
        f"{config_server.docling_ocr_engine}. "
        "Use auto, easyocr, mineru, surya, or rapidocr."
    )


def _docling_table_mode(config_server: ServerConfig) -> TableFormerMode:
    return TableFormerMode(config_server.docling_table_mode)


def _docling_timing_seconds(timing_item: object) -> float:
    return sum(float(value) for value in getattr(timing_item, "times", []) or [])


def _record_docling_timings(
    progress: ProgressReporter,
    timings: dict[str, object],
) -> None:
    for name, timing_item in timings.items():
        seconds = _docling_timing_seconds(timing_item)
        if seconds > 0:
            progress.record_timing(f"docling_{name}", seconds)


def _markdown_format_option() -> MarkdownFormatOption:
    return MarkdownFormatOption(
        pipeline_options=ConvertPipelineOptions(
            artifacts_path=None,
            enable_remote_services=False,
            allow_external_plugins=False,
        ),
        backend_options=MarkdownBackendOptions(
            enable_remote_fetch=False,
            enable_local_fetch=False,
            fetch_images=False,
        )
    )


def _json_markdown_title(source_file_name: str, source_path: Path) -> str:
    title = Path(source_file_name.replace("\\", "/")).stem
    return title or source_path.stem or "JSON document"


class DoclingParser(AbstractParser):
    """Parser implementation backed by Docling."""

    def parse(self, job: Job, progress: ProgressReporter) -> ParsedDocument:

        config_server: ServerConfig = self.server_config

        source_path = _job_source_path(job)
        source_file_name = str(job.input_data.get("file_name") or source_path.name)
        raw_mime_type = job.input_data.get("mime_type")
        input_format = _docling_input_format(
            source_path,
            str(raw_mime_type or ""),
        )
        mime_type = str(raw_mime_type or _default_mime_type(input_format))

        #Sacar las options del job o de la app

        threaded_pipeline_options = ThreadedPdfPipelineOptions(
            document_timeout=None,
            accelerator_options=AcceleratorOptions(
                num_threads=config_server.docling_accelerator_threads,
                device=config_server.docling_device,
                cuda_use_flash_attention2=False,
            ),

            # ---------------------------------------------------------------------
            # Security / external execution
            # ---------------------------------------------------------------------
            enable_remote_services=True,
            allow_external_plugins=True,

            # ---------------------------------------------------------------------
            # Local model artifacts
            # ---------------------------------------------------------------------
            artifacts_path=config_server.docling_artifacts_path,

            # ---------------------------------------------------------------------
            # Picture classification / description / chart extraction
            # Chart extraction uses Docling's Granite vision model, whose remote
            # HuggingFace code is incompatible with the installed Transformers
            # generation API and fails during document enrichment.
            # ---------------------------------------------------------------------
            do_picture_classification=(
                config_server.docling_picture_classification_enabled
            ),
            do_picture_description=config_server.docling_picture_description_enabled,
            do_chart_extraction=False,
            images_scale=config_server.docling_images_scale,

            # picture_classification_options= DocumentPictureClassifierOptions(),
            code_formula_options=CodeFormulaVlmOptions.from_preset('codeformulav2'),
            chart_extraction_options=ChartExtractionModelOptions(),
            #picture_classification_options=DocumentPictureClassifierOptions(),
            picture_description_options=PictureDescriptionApiOptions(
                prompt="Describe the image. Be concise and accurate. If the image is a diagram, generate a mermaid code diagram.",
                url=AnyUrl(config_server.docling_picture_description_url),
                params={
                    "model": config_server.docling_picture_description_model,
                    "temperature": 0.3,
                    "max_tokens": 16384,
                    "skip_special_tokens": False,
                },
                timeout=config_server.docling_picture_description_timeout,
                concurrency=config_server.docling_picture_description_concurrency,
            ),

            # ---------------------------------------------------------------------
            # Main PDF processing stages
            # ---------------------------------------------------------------------
            do_table_structure=True,
            do_ocr=config_server.docling_ocr_enabled,
            do_code_enrichment=config_server.docling_code_enrichment_enabled,
            do_formula_enrichment=config_server.docling_formula_enrichment_enabled,
            # Use backend-native PDF text instead of layout model text detection
            force_backend_text=False,

            # ---------------------------------------------------------------------
            # Table extraction
            # ---------------------------------------------------------------------
            table_structure_options=TableStructureOptions(
                do_cell_matching=True,
                mode=_docling_table_mode(config_server),
            ),
            # ---------------------------------------------------------------------
            # OCR
            # ---------------------------------------------------------------------

            ocr_options=_docling_ocr_options(config_server),

            # ---------------------------------------------------------------------
            # Layout analysis
            # ---------------------------------------------------------------------

            layout_options=PPDocLayoutV3Options(
                batch_size=config_server.docling_layout_batch_size,
                confidence_threshold=0.3,  # Filter low-confidence detections
                model_name=str(config_server.docling_pp_layout_model_path)

            ),

            # layout_options=LayoutOptions(
            #    keep_empty_clusters=False,
            #    skip_cell_assignment=False,
            #    create_orphan_clusters=True,
            #    model_spec=DOCLING_LAYOUT_HERON_101
            # ),

            # ---------------------------------------------------------------------
            # Threaded pipeline batching
            # ---------------------------------------------------------------------
            ocr_batch_size=config_server.docling_ocr_batch_size,
            layout_batch_size=config_server.docling_layout_batch_size,
            table_batch_size=config_server.docling_table_batch_size,
            batch_polling_interval_seconds=0.05,
            queue_max_size=config_server.docling_queue_max_size,
        )

        # backend_options = ThreadedDoclingParseBackendOptions(parser_threads=4, enable_remote_fetch=True, enable_local_fetch=False, release_native_memory_every_n_pages=256, kind="threaded-docling-parse")
        backend_options = PdfBackendOptions(enable_remote_fetch=True, enable_local_fetch=False, kind="pdf", )

        options = PdfFormatOption(
            backend=DoclingParseDocumentBackend,
            backend_options=backend_options,
            pipeline_options=threaded_pipeline_options,
            pipeline_cls=ProgressReportingStandardPdfPipeline)

        format_options = {
            InputFormat.PDF: options,
            InputFormat.MD: _markdown_format_option(),
        }
        converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF, InputFormat.MD],
            format_options=format_options)

        print("Starting conversion...")

        old_profile_pipeline_timings = (
            docling_settings.settings.debug.profile_pipeline_timings
        )
        old_artifacts_path = docling_settings.settings.artifacts_path
        docling_settings.settings.debug.profile_pipeline_timings = True
        if input_format in (InputFormat.MD, _JSON_INPUT_FORMAT):
            docling_settings.settings.artifacts_path = None
        with docling_progress(progress):
            try:
                if input_format == _JSON_INPUT_FORMAT:
                    markdown = JsonToMarkdownPreprocessor().from_file(
                        source_path,
                        title=_json_markdown_title(source_file_name, source_path),
                    )
                    conversion_result = converter.convert_string(
                        markdown,
                        format=InputFormat.MD,
                        name=Path(source_file_name).stem or source_path.stem,
                    )
                else:
                    conversion_result = converter.convert(source_path)
            finally:
                docling_settings.settings.debug.profile_pipeline_timings = (
                    old_profile_pipeline_timings
                )
                docling_settings.settings.artifacts_path = old_artifacts_path

        _record_docling_timings(
            progress,
            dict(getattr(conversion_result, "timings", {}) or {}),
        )
        doc = conversion_result.document
        docling_metadata = {
            "parser": "docling",
            "input_format": _input_format_value(input_format),
        }
        if input_format == _JSON_INPUT_FORMAT:
            docling_metadata["preprocessed_format"] = InputFormat.MD.value

        parsed_document = ParsedDocument(
            document_id=job.job_id,
            source_file_name=source_file_name,
            source_path=str(source_path),
            mime_type=mime_type,
            title=_document_title(doc, source_file_name=source_file_name),
            page_count=len(doc.pages),
            #markdown=doc.export_to_markdown(),
            #text=doc.export_to_text(),
            original_out_doc=DoclingOutputDocument(raw=doc),
            metadata={
                "docling": docling_metadata,
            },
        )
        progress.set_total_pages(parsed_document.page_count)

        return parsed_document
