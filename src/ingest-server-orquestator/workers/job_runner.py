# queues/workers/job_runner.py

from os import getpid
from pathlib import Path

from docling.backend.docling_parse_backend import DoclingParseDocumentBackend
from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice
from docling.datamodel.backend_options import PdfBackendOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.chart_extraction_options import ChartExtractionModelOptions
from docling.datamodel.layout_model_specs import DOCLING_LAYOUT_HERON_101
from docling.datamodel.pipeline_options import ThreadedPdfPipelineOptions, CodeFormulaVlmOptions, LayoutOptions, \
    granite_picture_description, OcrAutoOptions, TableStructureOptions, \
    TableFormerMode
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline
from docling_core.types.doc import ImageRefMode

from queues.domain.job import Job


def job_runner(job: Job) -> None:
    print(
        f"Processing job {job.job_id} in child PID {getpid()}",
        flush=True,
    )

    source = Path("/Users/aromlo1/Downloads/Retribuciones.pdf")

    threaded_pipeline_options = ThreadedPdfPipelineOptions(
        document_timeout=None,
        accelerator_options=AcceleratorOptions(
            num_threads=8,
            device=AcceleratorDevice.CPU,
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
        artifacts_path=None,

        # ---------------------------------------------------------------------
        # Picture classification / description / chart extraction
        # ---------------------------------------------------------------------
        do_picture_classification=True,
        do_picture_description=True,
        do_chart_extraction=True,


        # picture_classification_options= DocumentPictureClassifierOptions(),
        code_formula_options=CodeFormulaVlmOptions.from_preset('codeformulav2'),
        chart_extraction_options= ChartExtractionModelOptions(),
        picture_description_options = granite_picture_description,

        # ---------------------------------------------------------------------
        # Main PDF processing stages
        # ---------------------------------------------------------------------
        do_table_structure=True,
        do_ocr=False,
        do_code_enrichment=False,
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
        ocr_options=OcrAutoOptions(
            lang=[],  # example: ["en", "es"] or ["es"]
            force_full_page_ocr=False,
            bitmap_area_threshold=0.05,
        ),

        # ---------------------------------------------------------------------
        # Layout analysis
        # ---------------------------------------------------------------------

        layout_options=LayoutOptions(
            keep_empty_clusters=False,
            skip_cell_assignment=False,
            create_orphan_clusters=True,
            model_spec=DOCLING_LAYOUT_HERON_101
        ),


        # ---------------------------------------------------------------------
        # Threaded pipeline batching
        # ---------------------------------------------------------------------
        ocr_batch_size=8,
        layout_batch_size=4,
        table_batch_size=4,
        batch_polling_interval_seconds=0.1,
        queue_max_size=32,
    )

    threaded_pipeline_options.picture_description_options.prompt = (
        "Describe the image in four sentences. Be concise and accurate."
    )

    #threaded_backend_options = ThreadedDoclingParseBackendOptions(parser_threads=4, enable_remote_fetch=True, enable_local_fetch=False, kind="pdf")
    backend_options = PdfBackendOptions(enable_remote_fetch=True, enable_local_fetch=False, kind="pdf")

    options = PdfFormatOption(
        backend=DoclingParseDocumentBackend,
        backend_options=backend_options,
        pipeline_options=threaded_pipeline_options,
        pipeline_cls=StandardPdfPipeline)

    converter = DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={InputFormat.PDF: options})

    result = converter.convert(source)
    doc = result.document

    # Export to markdown
    markdown = doc.export_to_markdown(
        image_mode=ImageRefMode.PLACEHOLDER
    )

    # Save markdown in current execution folder
    output_path = Path.cwd() / f"{source.stem}-runner-mod.md"
    output_path.write_text(markdown, encoding="utf-8")

    print(f"Markdown generated at: {output_path}")

    #parser = get_parser(job.parser_name)
    #parser.process(job)

    print(
        f"Ended job {job.job_id} in child PID {getpid()}",
        flush=True,
    )
