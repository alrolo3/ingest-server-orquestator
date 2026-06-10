import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from docling_core.types.doc import BoundingBox, CoordOrigin

from processing.parsers.docling_progress import ProgressReportingStandardPdfPipeline
from processing.parsers.surya_ocr_model import (
    SuryaOcrModel,
    SuryaOcrOptions,
    _configure_surya_environment,
)


class SuryaOcrModelTest(unittest.TestCase):
    def test_block_to_text_cell_converts_image_bbox_to_page_coordinates(self) -> None:
        ocr_rect = BoundingBox(
            l=10,
            t=20,
            r=110,
            b=220,
            coord_origin=CoordOrigin.TOPLEFT,
        )

        cell = SuryaOcrModel.block_to_text_cell(
            {
                "html": "<p>Recognized <strong>text</strong></p>",
                "bbox": [20, 40, 100, 120],
                "confidence": 0.82,
            },
            image_size=(200, 400),
            ocr_rect=ocr_rect,
            index=3,
            scale=2.0,
            default_confidence=0.5,
        )

        self.assertIsNotNone(cell)
        assert cell is not None
        self.assertEqual(3, cell.index)
        self.assertEqual("Recognized text", cell.text)
        self.assertEqual(0.82, cell.confidence)
        self.assertTrue(cell.from_ocr)
        self.assertEqual(
            (20.0, 40.0, 60.0, 80.0),
            cell.rect.to_bounding_box().as_tuple(),
        )

    def test_block_to_text_cell_uses_polygon_and_default_confidence(self) -> None:
        ocr_rect = BoundingBox(
            l=0,
            t=0,
            r=100,
            b=100,
            coord_origin=CoordOrigin.TOPLEFT,
        )

        cell = SuryaOcrModel.block_to_text_cell(
            {
                "text": "Plain text",
                "polygon": [[-5, 10], [220, 10], [220, 100], [-5, 100]],
            },
            image_size=(200, 200),
            ocr_rect=ocr_rect,
            index=0,
            scale=2.0,
            default_confidence=0.7,
        )

        self.assertIsNotNone(cell)
        assert cell is not None
        self.assertEqual("Plain text", cell.text)
        self.assertEqual(0.7, cell.confidence)
        self.assertEqual(
            (0.0, 5.0, 100.0, 50.0),
            cell.rect.to_bounding_box().as_tuple(),
        )

    def test_block_to_text_cell_skips_unusable_blocks(self) -> None:
        ocr_rect = BoundingBox(
            l=0,
            t=0,
            r=100,
            b=100,
            coord_origin=CoordOrigin.TOPLEFT,
        )
        cases = [
            {"html": "<p>Skipped</p>", "bbox": [0, 0, 10, 10], "skipped": True},
            {"html": "<p>Error</p>", "bbox": [0, 0, 10, 10], "error": True},
            {"html": "", "bbox": [0, 0, 10, 10]},
            {"html": "<p>Bad bbox</p>", "bbox": [5, 5, 5, 10]},
        ]

        for block in cases:
            with self.subTest(block=block):
                cell = SuryaOcrModel.block_to_text_cell(
                    block,
                    image_size=(100, 100),
                    ocr_rect=ocr_rect,
                    index=0,
                    scale=1.0,
                    default_confidence=1.0,
                )

                self.assertIsNone(cell)

    def test_html_text_extraction_preserves_table_text(self) -> None:
        ocr_rect = BoundingBox(
            l=0,
            t=0,
            r=100,
            b=100,
            coord_origin=CoordOrigin.TOPLEFT,
        )

        cell = SuryaOcrModel.block_to_text_cell(
            {
                "html": (
                    "<table><tr><th>A</th><th>B</th></tr>"
                    "<tr><td>1</td><td>2</td></tr></table>"
                ),
                "bbox": [0, 0, 100, 50],
            },
            image_size=(100, 100),
            ocr_rect=ocr_rect,
            index=0,
            scale=1.0,
            default_confidence=1.0,
        )

        self.assertIsNotNone(cell)
        assert cell is not None
        self.assertEqual("A B\n1 2", cell.text)

    def test_progress_pipeline_uses_surya_model_for_surya_options(self) -> None:
        pipeline = object.__new__(ProgressReportingStandardPdfPipeline)
        pipeline.pipeline_options = SimpleNamespace(
            ocr_options=SuryaOcrOptions(lang=["es", "en"]),
            do_ocr=True,
            accelerator_options=object(),
            allow_external_plugins=True,
        )
        surya_model = object()

        with patch(
            "processing.parsers.docling_progress.SuryaOcrModel",
            return_value=surya_model,
        ) as surya:
            created_model = pipeline._make_ocr_model(Path("/tmp/artifacts"))

        self.assertIs(surya_model, created_model)
        surya.assert_called_once()

    def test_disabled_model_does_not_import_surya_runtime(self) -> None:
        model = SuryaOcrModel(
            enabled=False,
            artifacts_path=None,
            options=SuryaOcrOptions(),
            accelerator_options=MagicMock(),
        )
        pages = [object(), object()]

        self.assertEqual(pages, list(model(MagicMock(), pages)))

    def test_configure_surya_environment_sets_supported_settings(self) -> None:
        options = SuryaOcrOptions(
            inference_url=" http://surya:8000/v1 ",
            inference_backend=" vllm ",
            inference_parallel=0,
            keep_alive=False,
        )

        with patch.dict("os.environ", {}, clear=True):
            _configure_surya_environment(options)

            self.assertEqual("http://surya:8000/v1", os.environ["SURYA_INFERENCE_URL"])
            self.assertEqual("vllm", os.environ["SURYA_INFERENCE_BACKEND"])
            self.assertEqual("1", os.environ["SURYA_INFERENCE_PARALLEL"])
            self.assertEqual("0", os.environ["SURYA_INFERENCE_KEEP_ALIVE"])


if __name__ == "__main__":
    unittest.main()
