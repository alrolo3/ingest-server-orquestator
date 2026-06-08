# Changelog

All notable changes to this project should be documented in this file.

## [Unreleased]

### Added

- Added configurable Docling OCR settings for engine, languages, full-page OCR,
  bitmap area threshold, and OCR batch size.
- Added configurable ingest worker concurrency and Docling layout/table queue
  batch sizes for GPU memory control.
- Added the EasyOCR runtime dependency required by the default OCR engine.

### Changed

- Default OCR engine is offline EasyOCR with Spanish and English languages.
- Default EasyOCR runs on CPU to keep VRAM available for layout and VLM stages.
- Default ingest worker concurrency is one job at a time to avoid concurrent
  Docling GPU memory pressure.
- Reduced default Docling layout/table/OCR batch sizes for lower peak VRAM use.

### Fixed

- Set `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` before CUDA-backed
  libraries load to reduce fragmentation-related CUDA allocation failures.

## [0.1.0] - 2026-06-08

### Added

- Initial tracked changelog.
