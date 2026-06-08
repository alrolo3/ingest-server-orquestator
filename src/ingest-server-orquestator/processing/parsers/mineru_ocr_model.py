from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
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
_TEXT_BLOCK_TYPES = {
    "text",
    "title",
    "code",
    "algorithm",
    "aside_text",
    "ref_text",
    "phonetic",
    "list_item",
    "table_caption",
    "image_caption",
    "code_caption",
    "table_footnote",
    "image_footnote",
    "header",
    "footer",
    "page_number",
    "page_footnote",
}


class MinerUOcrOptions(OcrOptions):
    """Configuration for the local MinerU OCR adapter."""

    kind: ClassVar[Literal["mineru"]] = "mineru"
    lang: list[str] = Field(default_factory=lambda: ["es", "en"])
    model_path: str
    device: str = "auto"
    dtype: str = "auto"
    scale: float = 2.0
    confidence: float = 1.0
    batch_size: int = 1
    image_analysis: bool = False


class MinerU(BaseOcrModel):
    """Docling OCR stage backed by MinerU's Transformers backend."""

    def __init__(
        self,
        enabled: bool,
        artifacts_path: Path | None,
        options: MinerUOcrOptions,
        accelerator_options: AcceleratorOptions,
    ) -> None:
        super().__init__(
            enabled=enabled,
            artifacts_path=artifacts_path,
            options=options,
            accelerator_options=accelerator_options,
        )
        self.options: MinerUOcrOptions
        self.scale = self.options.scale

        if not self.enabled:
            return

        try:
            from mineru_vl_utils import MinerUClient
            from transformers import AutoProcessor, Qwen2VLForConditionalGeneration
        except ImportError as exc:
            raise ImportError(
                "MinerU OCR is not installed. Install `mineru-vl-utils` to use "
                "DOCLING_OCR_ENGINE=mineru."
            ) from exc

        model_path = Path(self.options.model_path)
        if not model_path.is_dir():
            LOGGER.warning("MinerU OCR model path is missing: %s", model_path)

        model = Qwen2VLForConditionalGeneration.from_pretrained(
            str(model_path),
            dtype=self.options.dtype,
            device_map=self._device_map(),
        )
        _ensure_max_position_embeddings(model)
        processor = AutoProcessor.from_pretrained(str(model_path), use_fast=True)
        self.client = MinerUClient(
            backend="transformers",
            model=model,
            processor=processor,
            batch_size=self.options.batch_size,
            use_tqdm=False,
        )

    def _device_map(self) -> str | dict[str, str]:
        device = self.options.device.strip().lower()
        if device == "auto":
            return "auto"
        return {"": self.options.device}

    def __call__(
        self,
        conv_res: ConversionResult,
        page_batch: Iterable[Page],
    ) -> Iterable[Page]:
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
                    blocks = self.client.two_step_extract(
                        image,
                        image_analysis=self.options.image_analysis,
                    )
                    for block in blocks:
                        cell = self.block_to_text_cell(
                            block,
                            image_size=image.size,
                            ocr_rect=ocr_rect,
                            index=len(all_ocr_cells),
                            scale=self.scale,
                            confidence=self.options.confidence,
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
        confidence: float,
    ) -> TextCell | None:
        block_type = _block_value(block, "type")
        content = _block_value(block, "content")
        bbox = _block_value(block, "bbox")

        if block_type not in _TEXT_BLOCK_TYPES:
            return None
        if not isinstance(content, str) or not content.strip():
            return None
        if not _valid_bbox(bbox):
            return None

        image_width, image_height = image_size
        x_min, y_min, x_max, y_max = [float(value) for value in bbox]
        return TextCell(
            index=index,
            text=content,
            orig=content,
            confidence=confidence,
            from_ocr=True,
            rect=BoundingRectangle.from_bounding_box(
                BoundingBox.from_tuple(
                    coord=(
                        ocr_rect.l + (x_min * image_width / scale),
                        ocr_rect.t + (y_min * image_height / scale),
                        ocr_rect.l + (x_max * image_width / scale),
                        ocr_rect.t + (y_max * image_height / scale),
                    ),
                    origin=CoordOrigin.TOPLEFT,
                )
            ),
        )

    @classmethod
    def get_options_type(cls) -> Type[OcrOptions]:
        return MinerUOcrOptions


def _block_value(block: Any, key: str) -> Any:
    if isinstance(block, Mapping):
        return block.get(key)
    return getattr(block, key, None)


def _ensure_max_position_embeddings(model: Any) -> None:
    config = getattr(model, "config", None)
    if config is None or hasattr(config, "max_position_embeddings"):
        return

    text_config = getattr(config, "text_config", None)
    max_position_embeddings = getattr(text_config, "max_position_embeddings", None)
    if not isinstance(max_position_embeddings, int) or max_position_embeddings <= 0:
        raise ValueError(
            "MinerU OCR model config does not expose max_position_embeddings "
            "or text_config.max_position_embeddings."
        )

    setattr(config, "max_position_embeddings", max_position_embeddings)
    LOGGER.debug(
        "Patched MinerU OCR model config max_position_embeddings=%s",
        max_position_embeddings,
    )


def _valid_bbox(value: Any) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, str) or len(value) != 4:
        return False
    try:
        x_min, y_min, x_max, y_max = [float(coord) for coord in value]
    except (TypeError, ValueError):
        return False
    return (
        0.0 <= x_min < x_max <= 1.0
        and 0.0 <= y_min < y_max <= 1.0
    )
