from pathlib import Path

from config.gpu import configure_gpu_environment

# Must run before importing Docling, EasyOCR, or other CUDA-backed dependencies.
configure_gpu_environment()

from docling.backend.docling_parse_backend import DoclingParseDocumentBackend
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.backend_options import PdfBackendOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.chart_extraction_options import ChartExtractionModelOptions
from docling.datamodel.pipeline_options import (
    CodeFormulaVlmOptions,
    EasyOcrOptions,
    OcrAutoOptions,
    PictureDescriptionApiOptions,
    RapidOcrOptions,
    TableFormerMode,
    TableStructureOptions,
    ThreadedPdfPipelineOptions,
)
from docling.document_converter import PdfFormatOption, DocumentConverter
from docling_core.types.doc.document import DocItemLabel, DoclingDocument
from docling_pp_doc_layout.options import PPDocLayoutV3Options
from pydantic import AnyUrl

from config.config import ServerConfig
from metrics.progress import ProgressReporter
from model.base_document import DoclingOutputDocument
from model.parsed_document import ParsedDocument
from processing.base_parser import AbstractParser
from processing.parsers.docling_progress import (
    ProgressReportingStandardPdfPipeline,
    docling_progress,
)
from processing.parsers.mineru_ocr_model import MinerUOcrOptions
from queues.domain.job import Job


def _document_title(doc: DoclingDocument) -> str | None:
    for text_item in doc.texts:
        if text_item.label == DocItemLabel.TITLE:
            title = text_item.text.strip()
            if title:
                return title
    title = doc.name.strip()
    return title if title else None


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
) -> OcrAutoOptions | EasyOcrOptions | RapidOcrOptions | MinerUOcrOptions:
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

    if engine == "rapidocr":
        rapid_options = dict(common_options)
        rapid_options["lang"] = _rapid_ocr_langs(config_server.docling_ocr_langs)
        return RapidOcrOptions(
            **rapid_options,
        )

    raise ValueError(
        "Unsupported DOCLING_OCR_ENGINE value: "
        f"{config_server.docling_ocr_engine}. Use auto, easyocr, mineru, or rapidocr."
    )


class DoclingParser(AbstractParser):
    """Parser implementation backed by Docling."""

    def parse(self, job: Job, progress: ProgressReporter) -> ParsedDocument:

        config_server: ServerConfig = self.server_config

        source_path = _job_source_path(job)
        source_file_name = str(job.input_data.get("file_name") or source_path.name)
        mime_type = str(job.input_data.get("mime_type") or "application/pdf")

        #Sacar las options del job o de la app

        threaded_pipeline_options = ThreadedPdfPipelineOptions(
            document_timeout=None,
            accelerator_options=AcceleratorOptions(
                num_threads=8,
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
            do_picture_classification=True,
            do_picture_description=True,
            do_chart_extraction=False,
            images_scale=2.0,

            # picture_classification_options= DocumentPictureClassifierOptions(),
            code_formula_options=CodeFormulaVlmOptions.from_preset('codeformulav2'),
            chart_extraction_options=ChartExtractionModelOptions(),
            #picture_classification_options=DocumentPictureClassifierOptions(),
            picture_description_options=PictureDescriptionApiOptions(
                prompt="Describe the image. Be concise and accurate. If the image is a diagram, generate a mermaid code diagram.",
                url=AnyUrl(config_server.docling_picture_description_url),
                params={
                    "model": "Qwen3.5-9B",
                    "temperature": 0.3,
                    "max_tokens": 16384,
                    "skip_special_tokens": False,
                },
                timeout=240,
                concurrency=16
            ),

            # ---------------------------------------------------------------------
            # Main PDF processing stages
            # ---------------------------------------------------------------------
            do_table_structure=True,
            do_ocr=config_server.docling_ocr_enabled,
            do_code_enrichment=True,
            do_formula_enrichment=False,
            # Use backend-native PDF text instead of layout model text detection
            force_backend_text=False,

            # ---------------------------------------------------------------------
            # Table extraction
            # ---------------------------------------------------------------------
            table_structure_options=TableStructureOptions(
                do_cell_matching=True,
                mode=TableFormerMode.ACCURATE
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

        converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF],
            format_options={InputFormat.PDF: options})

        print("Starting conversion...")

        with docling_progress(progress):
            doc = converter.convert(source_path).document

        parsed_document = ParsedDocument(
            document_id=job.job_id,
            source_file_name=source_file_name,
            source_path=str(source_path),
            mime_type=mime_type,
            title=_document_title(doc),
            page_count=len(doc.pages),
            #markdown=doc.export_to_markdown(),
            #text=doc.export_to_text(),
            original_out_doc=DoclingOutputDocument(raw=doc),
        )
        progress.set_total_pages(parsed_document.page_count)

        return parsed_document
