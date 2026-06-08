import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from config.config import ServerConfig
from model.base_document import AbstractOutputDocument
from model.parsed_document import ParsedDocument
from processing.chunking.docling_chunker import (
    ChunkMarkdownTableSerializer,
    DoclingChunker,
)

from docling_core.transforms.chunker.hierarchical_chunker import DocChunk, DocMeta
from docling_core.types.doc.base import BoundingBox
from docling_core.types.doc.document import (
    DocItemLabel,
    ProvenanceItem,
    TextItem,
)
from metrics.progress import NullProgressReporter


class FakeTokenizer:
    def count_tokens(self, text: str) -> int:
        return len(text.split())


class FakeDoclingChunker:
    tokenizer = FakeTokenizer()

    def __init__(self, chunks: list[DocChunk]) -> None:
        self._chunks = chunks

    def chunk(self, dl_doc: object) -> list[DocChunk]:
        return self._chunks

    def contextualize(self, *, chunk: DocChunk) -> str:
        headings = chunk.meta.headings or []
        return "\n".join([*headings, chunk.text])


class ChunkMarkdownTableSerializerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.serializer = ChunkMarkdownTableSerializer()

    def _split_table(self, table_text: str) -> tuple[str, list[str]]:
        header_lines, body_lines = self.serializer.get_header_and_body_lines(
            table_text=table_text
        )
        return "\n".join(header_lines), body_lines

    def test_simple_table_prefix_is_valid_markdown(self) -> None:
        prefix, body = self._split_table(
            "| A | B |\n"
            "|---|---|\n"
            "| 1 | 2 |\n"
        )

        self.assertEqual("| A | B |\n|---|---|\n", prefix)
        self.assertEqual(["| 1 | 2 |\n"], body)

    def test_captioned_table_prefix_keeps_caption_and_separator(self) -> None:
        prefix, body = self._split_table(
            "CUANTIAS COMPLEMENTOS ESPECIFICOS 2024\n\n"
            "| CUANTIA | CUANTIA |\n"
            "|---------|---------|\n"
            "| 1.042,44 | 14.594,16 |\n"
        )

        self.assertEqual(
            "CUANTIAS COMPLEMENTOS ESPECIFICOS 2024\n\n"
            "| CUANTIA | CUANTIA |\n"
            "|---------|---------|\n",
            prefix,
        )
        self.assertEqual(["| 1.042,44 | 14.594,16 |\n"], body)

    def test_extra_header_rows_are_repeated(self) -> None:
        prefix, body = self._split_table(
            "| COMPLEMENTO | COMPLEMENTO | TOTAL |\n"
            "|-------------|-------------|-------|\n"
            "| NIVEL | MES | ANO (*) |\n"
            "| 30 | 1.164,74 | 16.306,36 |\n"
        )

        self.assertEqual(
            "| COMPLEMENTO | COMPLEMENTO | TOTAL |\n"
            "|-------------|-------------|-------|\n"
            "| NIVEL | MES | ANO (*) |\n",
            prefix,
        )
        self.assertEqual(["| 30 | 1.164,74 | 16.306,36 |\n"], body)

    def test_label_rows_without_decimal_values_are_repeated(self) -> None:
        prefix, body = self._split_table(
            "| CUANTIA | CUANTIA | CUANTIA | CUANTIA |\n"
            "|---------|---------|---------|---------|\n"
            "| MENSUAL | ANUAL | MENSUAL | ANUAL |\n"
            "| 2.468,39 | 34.557,46 | 1.008,68 | 14.121,52 |\n"
        )

        self.assertIn("| MENSUAL | ANUAL | MENSUAL | ANUAL |\n", prefix)
        self.assertEqual(
            ["| 2.468,39 | 34.557,46 | 1.008,68 | 14.121,52 |\n"],
            body,
        )

    def test_numeric_rows_are_not_repeated_as_headers(self) -> None:
        prefix, body = self._split_table(
            "| NIVEL | MES | ANO |\n"
            "|-------|-----|-----|\n"
            "| 30 | 1.164,74 | 16.306,36 |\n"
            "| 29 | 1.044,71 | 14.625,94 |\n"
        )

        self.assertNotIn("| 30 | 1.164,74 | 16.306,36 |", prefix)
        self.assertEqual(
            [
                "| 30 | 1.164,74 | 16.306,36 |\n",
                "| 29 | 1.044,71 | 14.625,94 |\n",
            ],
            body,
        )


class DoclingChunkerTest(unittest.TestCase):
    def test_chunk_returns_fixed_rag_style_payload(self) -> None:
        item = TextItem(
            self_ref="#/texts/0",
            label=DocItemLabel.TEXT,
            prov=[
                ProvenanceItem(
                    page_no=2,
                    bbox=BoundingBox(l=0, t=0, r=1, b=1),
                    charspan=(0, 9),
                )
            ],
            orig="raw body",
            text="raw body",
        )
        doc_chunk = DocChunk(
            text="raw body",
            meta=DocMeta(
                doc_items=[item],
                headings=["Section"],
                captions=["Caption"],
            ),
        )
        chunker = DoclingChunker.model_construct(
            type="token",
            server_config=ServerConfig(
                app_name="test",
                environment="test",
                inbound_queue_name="queue",
                worker_max_workers=1,
                chunk_max_tokens=128,
                tokenizer_path=Path("/tmp/tokenizer"),
                docling_artifacts_path=Path("/tmp/docling-artifacts"),
                docling_pp_layout_model_path=Path("/tmp/pp-doclayout-v3"),
            ),
        )
        chunker._chunker = FakeDoclingChunker([doc_chunk])
        parsed_document = ParsedDocument(
            document_id="doc-1",
            source_file_name="sample.pdf",
            source_path="/tmp/sample.pdf",
            title="Sample document",
            page_count=12,
            metadata={"docling": {"parser": "docling", "input_format": "pdf"}},
            original_out_doc=AbstractOutputDocument(raw=object()),
        )

        chunks = chunker.chunk(parsed_document, NullProgressReporter())

        self.assertEqual(1, len(chunks))
        chunk = chunks[0]
        self.assertEqual("Section\nraw body", chunk.content)
        self.assertEqual("doc-1", chunk.document_id)
        self.assertEqual("doc-1-00000", chunk.chunk_id)
        self.assertEqual(0, chunk.chunk_index)
        self.assertEqual("token", chunk.chunking_strategy)
        self.assertEqual(3, chunk.content_token_count)
        self.assertEqual(["#/texts/0"], chunk.doc_items)
        self.assertEqual(2, chunk.page_number)
        self.assertEqual([2], chunk.page_numbers)
        self.assertEqual(12, chunk.total_pages)
        self.assertEqual("Sample document", chunk.title)
        self.assertEqual("sample.pdf", chunk.source_file_name)
        self.assertEqual("raw body", chunk.raw_text)
        self.assertEqual("Section\nraw body", chunk.model_dump()["content"])
        self.assertNotIn("text", chunk.model_dump())
        self.assertNotIn("metadata", chunk.model_dump())


if __name__ == "__main__":
    unittest.main()
