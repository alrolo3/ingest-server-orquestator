import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from model.title_normalization import normalize_document_title


class TitleNormalizationTest(unittest.TestCase):
    def test_strips_upload_hex_uuid_prefix(self) -> None:
        title = normalize_document_title(
            "7b6c94b653dc44d3b5bc68c5d080189a-guia-notificacion-ciberincidentes"
        )

        self.assertEqual("guia-notificacion-ciberincidentes", title)

    def test_strips_canonical_uuid_prefix_and_extension(self) -> None:
        title = normalize_document_title(
            "550e8400-e29b-41d4-a716-446655440000-guia.pdf",
            strip_extension=True,
        )

        self.assertEqual("guia", title)

    def test_strips_path_and_known_document_extension_when_requested(self) -> None:
        title = normalize_document_title(
            "/uploads/7b6c94b653dc44d3b5bc68c5d080189a-guia.pdf",
            strip_extension=True,
        )

        self.assertEqual("guia", title)

    def test_keeps_normal_human_title(self) -> None:
        title = normalize_document_title("Guia de notificacion de ciberincidentes")

        self.assertEqual("Guia de notificacion de ciberincidentes", title)


if __name__ == "__main__":
    unittest.main()
