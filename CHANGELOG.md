# Changelog

All notable changes to this project should be documented in this file.

## [Unreleased]

### Added

- Added configurable Docling OCR settings for engine, languages, full-page OCR,
  bitmap area threshold, and OCR batch size.
- Added configurable ingest worker concurrency and Docling layout/table queue
  batch sizes for GPU memory control.
- Added deployment config for enabling Docling code enrichment with
  `DOCLING_CODE_ENRICHMENT_ENABLED`.
- Added the EasyOCR runtime dependency required by the default OCR engine.
- Added a configurable MinerU OCR backend for Docling, selected with
  `DOCLING_OCR_ENGINE=mineru`.
- Added the MinerU utility runtime dependency without changing the pinned
  Transformers version.
- Added a configurable Surya OCR 2 backend for Docling, selected with
  `DOCLING_OCR_ENGINE=surya`.
- Added a k3s Surya OCR 2 vLLM deployment and service for offline inference.
- Added a LiteLLM model route for `datalab-to/surya-ocr-2`.
- Added cleaned title semantic retrieval and a backfill artifact for existing
  RAG chunks.

### Changed

- Application fallback OCR engine is offline EasyOCR with Spanish and English
  languages when no deployment override is provided.
- Default EasyOCR runs on CPU to keep VRAM available for layout and VLM stages.
- Default ingest worker concurrency is one job at a time to avoid concurrent
  Docling GPU memory pressure.
- Reduced default Docling layout/table/OCR batch sizes for lower peak VRAM use.
- k3s ingest configuration now uses Surya OCR 2 through
  `DOCLING_SURYA_INFERENCE_URL=http://surya-vllm:8000/v1`.

### Fixed

- Set `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` before CUDA-backed
  libraries load to reduce fragmentation-related CUDA allocation failures.

## [0.1.0] - 2026-06-08

### Added

- Initial tracked changelog.
