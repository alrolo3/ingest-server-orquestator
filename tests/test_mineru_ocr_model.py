import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from docling_core.types.doc import BoundingBox, CoordOrigin

from processing.parsers.docling_progress import ProgressReportingStandardPdfPipeline
from processing.parsers.mineru_ocr_model import MinerU, MinerUOcrOptions


class MinerUOcrModelTest(unittest.TestCase):
    def test_block_to_text_cell_converts_normalized_bbox_to_page_coordinates(self) -> None:
        ocr_rect = BoundingBox(
            l=10,
            t=20,
            r=110,
            b=220,
            coord_origin=CoordOrigin.TOPLEFT,
        )

        cell = MinerU.block_to_text_cell(
            {"type": "text", "content": "Recognized text", "bbox": [0.1, 0.2, 0.5, 0.6]},
            image_size=(200, 400),
            ocr_rect=ocr_rect,
            index=3,
            scale=2.0,
            confidence=0.8,
        )

        self.assertIsNotNone(cell)
        assert cell is not None
        self.assertEqual(3, cell.index)
        self.assertEqual("Recognized text", cell.text)
        self.assertEqual(0.8, cell.confidence)
        self.assertTrue(cell.from_ocr)
        self.assertEqual(
            (20.0, 60.0, 60.0, 140.0),
            cell.rect.to_bounding_box().as_tuple(),
        )

    def test_block_to_text_cell_skips_non_text_blocks(self) -> None:
        ocr_rect = BoundingBox(
            l=0,
            t=0,
            r=100,
            b=100,
            coord_origin=CoordOrigin.TOPLEFT,
        )

        cell = MinerU.block_to_text_cell(
            {"type": "table", "content": "<table></table>", "bbox": [0.0, 0.0, 1.0, 1.0]},
            image_size=(100, 100),
            ocr_rect=ocr_rect,
            index=0,
            scale=1.0,
            confidence=1.0,
        )

        self.assertIsNone(cell)

    def test_progress_pipeline_uses_mineru_model_for_mineru_options(self) -> None:
        pipeline = object.__new__(ProgressReportingStandardPdfPipeline)
        pipeline.pipeline_options = SimpleNamespace(
            ocr_options=MinerUOcrOptions(lang=["es", "en"], model_path="/tmp/mineru"),
            do_ocr=True,
            accelerator_options=object(),
            allow_external_plugins=True,
        )
        mineru_model = object()

        with patch("processing.parsers.docling_progress.MinerU", return_value=mineru_model) as mineru:
            created_model = pipeline._make_ocr_model(Path("/tmp/artifacts"))

        self.assertIs(mineru_model, created_model)
        mineru.assert_called_once()

    def test_progress_pipeline_delegates_other_ocr_options_to_docling_factory(self) -> None:
        pipeline = object.__new__(ProgressReportingStandardPdfPipeline)
        ocr_options = object()
        pipeline.pipeline_options = SimpleNamespace(
            ocr_options=ocr_options,
            do_ocr=True,
            accelerator_options=object(),
            allow_external_plugins=True,
        )
        created_model = object()
        factory = MagicMock()
        factory.create_instance.return_value = created_model

        with patch("processing.parsers.docling_progress.get_ocr_factory", return_value=factory):
            result = pipeline._make_ocr_model(Path("/tmp/artifacts"))

        self.assertIs(created_model, result)
        factory.create_instance.assert_called_once()


if __name__ == "__main__":
    unittest.main()
