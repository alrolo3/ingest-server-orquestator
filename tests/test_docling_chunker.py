import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from config.config import ServerConfig
from model.base_document import AbstractOutputDocument
from model.parsed_document import ParsedDocument
from processing.chunking.docling_chunker import (
    CHUNK_OVERLAP_TOKENS,
    ChunkMarkdownTableSerializer,
    DoclingChunker,
    MARKDOWN_SINGLE_CHUNK_MAX_TOKENS,
    SPARSE_CHUNK_MAX_TOKENS,
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

    def get_tokenizer(self) -> "FakeTokenizer":
        return self

    def encode(self, text: str, add_special_tokens: bool = False) -> list[str]:
        return text.split()

    def decode(self, token_ids: list[str], skip_special_tokens: bool = True) -> str:
        return " ".join(token_ids)


class FakeDoclingChunker:
    tokenizer = FakeTokenizer()

    def __init__(self, chunks: list[DocChunk]) -> None:
        self._chunks = chunks
        self.chunk_calls = 0

    def chunk(self, dl_doc: object) -> list[DocChunk]:
        self.chunk_calls += 1
        return self._chunks

    def contextualize(self, *, chunk: DocChunk) -> str:
        headings = chunk.meta.headings or []
        return "\n".join([*headings, chunk.text])


class FakeMarkdownDocument:
    def __init__(self, markdown: str) -> None:
        self._markdown = markdown

    def export_to_markdown(self) -> str:
        return self._markdown


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
    def test_sparse_chunk_limit_is_512_tokens_with_100_token_overlap(self) -> None:
        self.assertEqual(512, SPARSE_CHUNK_MAX_TOKENS)
        self.assertEqual(100, CHUNK_OVERLAP_TOKENS)
        self.assertEqual(SPARSE_CHUNK_MAX_TOKENS, MARKDOWN_SINGLE_CHUNK_MAX_TOKENS)

    def test_hybrid_chunker_uses_existing_tokenizer_with_sparse_safe_limit(self) -> None:
        config = ServerConfig(
            app_name="test",
            environment="test",
            inbound_queue_name="queue",
            worker_max_workers=1,
            chunk_max_tokens=8192,
            tokenizer_path=Path("/tmp/tokenizer"),
            docling_artifacts_path=Path("/tmp/docling-artifacts"),
            docling_pp_layout_model_path=Path("/tmp/pp-doclayout-v3"),
        )

        with patch.object(
            DoclingChunker,
            "_build_token_chunker",
            return_value=FakeDoclingChunker([]),
        ) as build_chunker:
            DoclingChunker(
                server_config=config,
                tokenizer_path="/tmp/tokenizer",
                type_="token",
            )

        build_chunker.assert_called_once_with(
            tokenizer_path="/tmp/tokenizer",
            max_tokens=SPARSE_CHUNK_MAX_TOKENS,
        )

    def test_hybrid_chunker_preserves_lower_configured_limit(self) -> None:
        config = ServerConfig(
            app_name="test",
            environment="test",
            inbound_queue_name="queue",
            worker_max_workers=1,
            chunk_max_tokens=128,
            tokenizer_path=Path("/tmp/tokenizer"),
            docling_artifacts_path=Path("/tmp/docling-artifacts"),
            docling_pp_layout_model_path=Path("/tmp/pp-doclayout-v3"),
        )

        with patch.object(
            DoclingChunker,
            "_build_token_chunker",
            return_value=FakeDoclingChunker([]),
        ) as build_chunker:
            DoclingChunker(
                server_config=config,
                tokenizer_path="/tmp/tokenizer",
                type_="token",
            )

        build_chunker.assert_called_once_with(
            tokenizer_path="/tmp/tokenizer",
            max_tokens=128,
        )

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
        self.assertEqual("Sample document", chunk.clean_title)
        self.assertEqual(["Section"], chunk.headings)
        self.assertEqual("sample.pdf", chunk.source_file_name)
        self.assertEqual("Section\nraw body", chunk.model_dump()["content"])
        self.assertEqual("Section\nraw body", chunk.model_dump()["content_sparse"])
        self.assertNotIn("text", chunk.model_dump())
        self.assertNotIn("metadata", chunk.model_dump())
        self.assertNotIn("title_semantic", chunk.model_dump())
        self.assertNotIn("raw_text", chunk.model_dump())

    def test_chunk_uploads_small_markdown_as_single_chunk(self) -> None:
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
        fake_chunker = FakeDoclingChunker([])
        chunker._chunker = fake_chunker
        parsed_document = ParsedDocument(
            document_id="doc-1",
            source_file_name="sample.md",
            source_path="/tmp/sample.md",
            title="Sample markdown",
            page_count=0,
            metadata={"docling": {"parser": "docling", "input_format": "md"}},
            original_out_doc=AbstractOutputDocument(
                raw=FakeMarkdownDocument("# Introduction\n\nSmall markdown body")
            ),
        )

        chunks = chunker.chunk(parsed_document, NullProgressReporter())

        self.assertEqual(0, fake_chunker.chunk_calls)
        self.assertEqual(1, len(chunks))
        chunk = chunks[0]
        self.assertEqual("# Introduction\n\nSmall markdown body", chunk.content)
        self.assertEqual(5, chunk.content_token_count)
        self.assertEqual([], chunk.doc_items)
        self.assertIsNone(chunk.page_number)
        self.assertEqual([], chunk.page_numbers)
        self.assertEqual(0, chunk.total_pages)
        self.assertEqual(["Introduction"], chunk.headings)
        self.assertEqual("sample.md", chunk.source_file_name)

    def test_chunk_uses_docling_chunker_for_large_markdown_without_pages(self) -> None:
        item = TextItem(
            self_ref="#/texts/0",
            label=DocItemLabel.TEXT,
            prov=[],
            orig="markdown body",
            text="markdown body",
        )
        doc_chunk = DocChunk(
            text="markdown body",
            meta=DocMeta(
                doc_items=[item],
                headings=["Introduction"],
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
        fake_chunker = FakeDoclingChunker([doc_chunk])
        chunker._chunker = fake_chunker
        parsed_document = ParsedDocument(
            document_id="doc-1",
            source_file_name="sample.md",
            source_path="/tmp/sample.md",
            title="Sample markdown",
            page_count=0,
            metadata={"docling": {"parser": "docling", "input_format": "md"}},
            original_out_doc=AbstractOutputDocument(
                raw=FakeMarkdownDocument(
                    "# Introduction\n\n"
                    + "word " * (MARKDOWN_SINGLE_CHUNK_MAX_TOKENS + 1)
                )
            ),
        )

        chunks = chunker.chunk(parsed_document, NullProgressReporter())

        self.assertEqual(1, fake_chunker.chunk_calls)
        self.assertEqual(1, len(chunks))
        chunk = chunks[0]
        self.assertEqual("Introduction\nmarkdown body", chunk.content)
        self.assertEqual(["#/texts/0"], chunk.doc_items)
        self.assertIsNone(chunk.page_number)
        self.assertEqual([], chunk.page_numbers)
        self.assertEqual(0, chunk.total_pages)
        self.assertEqual("Sample markdown", chunk.clean_title)
        self.assertEqual(["Introduction"], chunk.headings)
        self.assertEqual("sample.md", chunk.source_file_name)

    def test_chunk_splits_contextualized_content_over_sparse_limit(self) -> None:
        item = TextItem(
            self_ref="#/texts/0",
            label=DocItemLabel.TEXT,
            prov=[],
            orig="raw body",
            text="raw body",
        )
        words = [f"word{i}" for i in range((SPARSE_CHUNK_MAX_TOKENS * 2) + 16)]
        doc_chunk = DocChunk(
            text=" ".join(words),
            meta=DocMeta(
                doc_items=[item],
                headings=["Section"],
            ),
        )
        chunker = DoclingChunker.model_construct(
            type="token",
            server_config=ServerConfig(
                app_name="test",
                environment="test",
                inbound_queue_name="queue",
                worker_max_workers=1,
                chunk_max_tokens=8192,
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
            page_count=1,
            metadata={"docling": {"parser": "docling", "input_format": "pdf"}},
            original_out_doc=AbstractOutputDocument(raw=object()),
        )

        chunks = chunker.chunk(parsed_document, NullProgressReporter())

        self.assertEqual(3, len(chunks))
        self.assertEqual([0, 1, 2], [chunk.chunk_index for chunk in chunks])
        self.assertEqual(
            ["doc-1-00000", "doc-1-00001", "doc-1-00002"],
            [chunk.chunk_id for chunk in chunks],
        )
        self.assertEqual(
            [SPARSE_CHUNK_MAX_TOKENS, SPARSE_CHUNK_MAX_TOKENS, 217],
            [chunk.content_token_count for chunk in chunks],
        )
        self.assertEqual(
            chunks[0].content.split()[-CHUNK_OVERLAP_TOKENS:],
            chunks[1].content.split()[:CHUNK_OVERLAP_TOKENS],
        )
        self.assertEqual(
            chunks[1].content.split()[-CHUNK_OVERLAP_TOKENS:],
            chunks[2].content.split()[:CHUNK_OVERLAP_TOKENS],
        )
        for chunk in chunks:
            self.assertLessEqual(
                chunk.content_token_count or 0,
                SPARSE_CHUNK_MAX_TOKENS,
            )
            self.assertEqual(chunk.content, chunk.content_sparse)


if __name__ == "__main__":
    unittest.main()
