from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping, Sequence
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar, Literal, Type

from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import Page
from docling.datamodel.document import ConversionResult
from docling.datamodel.pipeline_options import OcrOptions
from docling.datamodel.settings import settings
from docling.models.base_ocr_model import BaseOcrModel
from docling.utils.profiling import TimeRecorder
from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell
from pydantic import Field


LOGGER = logging.getLogger(__name__)


class SuryaOcrOptions(OcrOptions):
    """Configuration for the local Surya OCR 2 adapter."""

    kind: ClassVar[Literal["surya"]] = "surya"
    lang: list[str] = Field(default_factory=lambda: ["es", "en"])
    scale: float = 2.0
    confidence: float = 1.0
    inference_url: str | None = None
    inference_backend: str | None = None
    inference_parallel: int = 8
    keep_alive: bool = True


class SuryaOcrModel(BaseOcrModel):
    """Docling OCR stage backed by Surya OCR 2's VLM inference client."""

    def __init__(
        self,
        enabled: bool,
        artifacts_path: Path | None,
        options: SuryaOcrOptions,
        accelerator_options: AcceleratorOptions,
    ) -> None:
        super().__init__(
            enabled=enabled,
            artifacts_path=artifacts_path,
            options=options,
            accelerator_options=accelerator_options,
        )
        self.options: SuryaOcrOptions
        self.scale = self.options.scale

        if not self.enabled:
            return

        _configure_surya_environment(self.options)
        try:
            from surya.inference import SuryaInferenceManager
            from surya.recognition import RecognitionPredictor
            from surya.settings import settings as surya_settings
        except ImportError as exc:
            raise ImportError(
                "Surya OCR is not installed. Install `surya-ocr` to use "
                "DOCLING_OCR_ENGINE=surya."
            ) from exc

        _configure_surya_settings(surya_settings, self.options)
        self.manager = SuryaInferenceManager(
            method=_clean_optional(self.options.inference_backend),
        )
        self.predictor = RecognitionPredictor(self.manager)
        self.predictor.disable_tqdm = True

    def __call__(
        self,
        conv_res: ConversionResult,
        page_batch: Iterable[Page],
    ) -> Iterable[Page]:
        """Run Surya OCR on Docling OCR rectangles and attach TextCell results."""
        if not self.enabled:
            yield from page_batch
            return

        for page in page_batch:
            assert page._backend is not None
            if not page._backend.is_valid():
                yield page
                continue

            with TimeRecorder(conv_res, "ocr"):
                ocr_rects = self.get_ocr_rects(page)
                all_ocr_cells: list[TextCell] = []

                for ocr_rect in ocr_rects:
                    if ocr_rect.area() == 0:
                        continue

                    image = page._backend.get_page_image(
                        scale=self.scale,
                        cropbox=ocr_rect,
                    )
                    page_results = self.predictor([image], full_page=True)
                    page_result = page_results[0] if page_results else None
                    blocks = getattr(page_result, "blocks", []) if page_result else []
                    for block in blocks:
                        cell = self.block_to_text_cell(
                            block,
                            image_size=image.size,
                            ocr_rect=ocr_rect,
                            index=len(all_ocr_cells),
                            scale=self.scale,
                            default_confidence=self.options.confidence,
                        )
                        if cell is not None:
                            all_ocr_cells.append(cell)

                    del image

                self.post_process_cells(all_ocr_cells, page)

            if settings.debug.visualize_ocr:
                self.draw_ocr_rects_and_cells(conv_res, page, ocr_rects)

            yield page

    @staticmethod
    def block_to_text_cell(
        block: Any,
        image_size: tuple[int, int],
        ocr_rect: BoundingBox,
        index: int,
        scale: float,
        default_confidence: float,
    ) -> TextCell | None:
        """Convert one Surya result block into Docling page coordinates."""
        if _truthy_block_value(block, "skipped") or _truthy_block_value(block, "error"):
            return None

        text = _block_text(block)
        if not text:
            return None

        bbox = _block_bbox(block, image_size)
        if bbox is None:
            return None

        x_min, y_min, x_max, y_max = bbox
        confidence = _block_confidence(block, default_confidence)
        return TextCell(
            index=index,
            text=text,
            orig=text,
            confidence=confidence,
            from_ocr=True,
            rect=BoundingRectangle.from_bounding_box(
                BoundingBox.from_tuple(
                    coord=(
                        ocr_rect.l + (x_min / scale),
                        ocr_rect.t + (y_min / scale),
                        ocr_rect.l + (x_max / scale),
                        ocr_rect.t + (y_max / scale),
                    ),
                    origin=CoordOrigin.TOPLEFT,
                )
            ),
        )

    @classmethod
    def get_options_type(cls) -> Type[OcrOptions]:
        return SuryaOcrOptions


def _configure_surya_environment(options: SuryaOcrOptions) -> None:
    inference_url = _required_inference_url(options)
    os.environ["SURYA_INFERENCE_URL"] = inference_url

    inference_backend = _clean_optional(options.inference_backend)
    if inference_backend is not None:
        os.environ["SURYA_INFERENCE_BACKEND"] = inference_backend

    os.environ["SURYA_INFERENCE_PARALLEL"] = str(max(1, options.inference_parallel))
    os.environ["SURYA_INFERENCE_KEEP_ALIVE"] = "1" if options.keep_alive else "0"


def _configure_surya_settings(settings_object: Any, options: SuryaOcrOptions) -> None:
    inference_url = _required_inference_url(options)
    setattr(settings_object, "SURYA_INFERENCE_URL", inference_url)

    inference_backend = _clean_optional(options.inference_backend)
    if inference_backend is not None:
        setattr(settings_object, "SURYA_INFERENCE_BACKEND", inference_backend)

    setattr(
        settings_object,
        "SURYA_INFERENCE_PARALLEL",
        max(1, options.inference_parallel),
    )
    setattr(settings_object, "SURYA_INFERENCE_KEEP_ALIVE", options.keep_alive)


def _required_inference_url(options: SuryaOcrOptions) -> str:
    inference_url = _clean_optional(options.inference_url)
    if inference_url is None:
        raise ValueError(
            "DOCLING_SURYA_INFERENCE_URL must be set when "
            "DOCLING_OCR_ENGINE=surya. Point it at the Surya vLLM or llama.cpp "
            "OpenAI-compatible /v1 endpoint."
        )
    return inference_url


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _block_value(block: Any, key: str) -> Any:
    if isinstance(block, Mapping):
        return block.get(key)
    return getattr(block, key, None)


def _truthy_block_value(block: Any, key: str) -> bool:
    value = _block_value(block, key)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _block_text(block: Any) -> str | None:
    text = _block_value(block, "text")
    if isinstance(text, str) and text.strip():
        return _normalize_text(text)

    html_text = _block_value(block, "html")
    if isinstance(html_text, str) and html_text.strip():
        return _html_to_text(html_text)

    return None


def _block_bbox(
    block: Any,
    image_size: tuple[int, int],
) -> tuple[float, float, float, float] | None:
    bbox = _bbox_tuple(_block_value(block, "bbox"))
    if bbox is None:
        bbox = _bbox_from_polygon(_block_value(block, "polygon"))
    if bbox is None:
        return None
    return _clamp_bbox(bbox, image_size)


def _bbox_tuple(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, Sequence) or isinstance(value, str) or len(value) != 4:
        return None
    try:
        x_min, y_min, x_max, y_max = [float(coord) for coord in value]
    except (TypeError, ValueError):
        return None
    if x_min >= x_max or y_min >= y_max:
        return None
    return x_min, y_min, x_max, y_max


def _bbox_from_polygon(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, Sequence) or isinstance(value, str) or not value:
        return None

    points: list[tuple[float, float]] = []
    for point in value:
        if (
            not isinstance(point, Sequence)
            or isinstance(point, str)
            or len(point) != 2
        ):
            return None
        try:
            points.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError):
            return None

    x_values = [point[0] for point in points]
    y_values = [point[1] for point in points]
    return min(x_values), min(y_values), max(x_values), max(y_values)


def _clamp_bbox(
    bbox: tuple[float, float, float, float],
    image_size: tuple[int, int],
) -> tuple[float, float, float, float] | None:
    image_width, image_height = image_size
    x_min, y_min, x_max, y_max = bbox
    x_min = max(0.0, min(float(image_width), x_min))
    y_min = max(0.0, min(float(image_height), y_min))
    x_max = max(0.0, min(float(image_width), x_max))
    y_max = max(0.0, min(float(image_height), y_max))
    if x_min >= x_max or y_min >= y_max:
        return None
    return x_min, y_min, x_max, y_max


def _block_confidence(block: Any, default_confidence: float) -> float:
    value = _block_value(block, "confidence")
    try:
        return float(value)
    except (TypeError, ValueError):
        return default_confidence


class _PlainTextHTMLParser(HTMLParser):
    """Tiny HTML-to-text helper for Surya blocks that return table-like HTML."""

    _BLOCK_TAGS = {
        "article",
        "blockquote",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "p",
        "section",
        "table",
        "tr",
    }
    _INLINE_SEPARATOR_TAGS = {"td", "th"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._BLOCK_TAGS:
            self._append_separator("\n")
        elif tag in self._INLINE_SEPARATOR_TAGS:
            self._append_separator(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCK_TAGS:
            self._append_separator("\n")
        elif tag in self._INLINE_SEPARATOR_TAGS:
            self._append_separator(" ")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)

    def _append_separator(self, separator: str) -> None:
        if not self._parts:
            return
        current = self._parts[-1]
        if current.endswith(separator) or current.endswith("\n"):
            return
        self._parts.append(separator)


def _html_to_text(value: str) -> str | None:
    parser = _PlainTextHTMLParser()
    parser.feed(value)
    parser.close()
    return _normalize_text(parser.get_text())


def _normalize_text(value: str) -> str | None:
    lines = [" ".join(line.split()) for line in value.splitlines()]
    text = "\n".join(line for line in lines if line)
    return text or None
