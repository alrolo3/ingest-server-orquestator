import re
from functools import lru_cache
from typing import Any

from docling.chunking import HybridChunker
from docling_core.transforms.chunker.hierarchical_chunker import (
    ChunkingDocSerializer,
    ChunkingSerializerProvider,
    DocChunk,
)
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.transforms.serializer.markdown import MarkdownTableSerializer
from docling_core.types import DoclingDocument
from pydantic import PrivateAttr
from transformers import AutoTokenizer

from config.config import ServerConfig
from model.document_chunk import DocumentChunk
from model.parsed_document import ParsedDocument
from processing.base_chunker import AbstractChunker


_DECIMAL_NUMBER_RE = re.compile(r"\d+(?:\.\d{3})*,\d+")
_INTEGER_RE = re.compile(r"\d+")


def _docling_chunk_refs(chunk: DocChunk) -> tuple[list[str], list[int]]:
    doc_items = chunk.meta.doc_items
    item_refs = []
    pages = []
    for item in doc_items:
        item_refs.append(str(item.self_ref))
        for prov in item.prov:
            pages.append(prov.page_no)
    return list(dict.fromkeys(item_refs)), sorted(set(pages))


def _markdown_table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or "|" not in stripped[1:]:
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _is_markdown_table_separator(line: str) -> bool:
    cells = _markdown_table_cells(line)
    return bool(cells) and all(cell and set(cell) <= {"-", ":"} for cell in cells)


def _is_header_like_table_row(line: str) -> bool:
    cells = [cell for cell in _markdown_table_cells(line) if cell]
    if not cells:
        return False
    if any(_DECIMAL_NUMBER_RE.search(cell) for cell in cells):
        return False

    numeric_cells = sum(1 for cell in cells if _INTEGER_RE.fullmatch(cell))
    label_cells = len(cells) - numeric_cells
    return label_cells >= max(1, len(cells) // 2)


class ChunkMarkdownTableSerializer(MarkdownTableSerializer):
    """Markdown table serializer with chunk-safe repeated headers."""

    def get_header_and_body_lines(
        self,
        *,
        table_text: str,
        **kwargs: Any,
    ) -> tuple[list[str], list[str]]:
        lines = [line for line in table_text.splitlines(True) if line.strip()]
        normalized_lines = [line.rstrip("\r\n") for line in lines]

        separator_index = next(
            (
                index
                for index, line in enumerate(normalized_lines)
                if _is_markdown_table_separator(line)
            ),
            None,
        )
        if separator_index is None or separator_index == 0:
            return [], lines

        header_index = separator_index - 1
        body_start_index = separator_index + 1
        while (
            body_start_index < len(normalized_lines)
            and _is_header_like_table_row(normalized_lines[body_start_index])
        ):
            body_start_index += 1

        header_lines = normalized_lines[:header_index]
        if header_lines:
            header_lines.append("")
        header_lines.extend(normalized_lines[header_index:body_start_index])
        header_lines[-1] = f"{header_lines[-1]}\n"

        return header_lines, lines[body_start_index:]


class MarkdownChunkingSerializerProvider(ChunkingSerializerProvider):
    """Keep Docling chunk metadata behavior while serializing tables as markdown."""

    def get_serializer(self, doc: DoclingDocument) -> ChunkingDocSerializer:
        return ChunkingDocSerializer(
            doc=doc,
            table_serializer=ChunkMarkdownTableSerializer(),
        )


class DoclingChunker(AbstractChunker):
    """Chunker implementation backed by Docling."""

    _chunker: HybridChunker = PrivateAttr()

    def __init__(
        self,
        type: str,
        server_config: ServerConfig,
        tokenizer_path: str,
    ) -> None:
        super().__init__(
            type=type,
            server_config=server_config,
        )

        if type != "token":
            raise ValueError(f"Unsupported Docling chunk type: {type}")
        if server_config.chunk_max_tokens <= 0:
            raise ValueError("chunk_max_tokens must be greater than zero")

        self._chunker = self._build_token_chunker(
            tokenizer_path=str(tokenizer_path),
            max_tokens=server_config.chunk_max_tokens,
        )

    @staticmethod
    @lru_cache(maxsize=8)
    def _build_token_chunker(tokenizer_path: str, max_tokens: int) -> HybridChunker:
        tokenizer = AutoTokenizer.from_pretrained(
            tokenizer_path,
            local_files_only=True,
        )
        hf_tokenizer = HuggingFaceTokenizer(
            tokenizer=tokenizer,
            max_tokens=max_tokens,
        )
        return HybridChunker(
            tokenizer=hf_tokenizer,
            repeat_table_header=True,
            omit_header_on_overflow=True,
            merge_peers=True,
            serializer_provider=MarkdownChunkingSerializerProvider(),
        )

    def chunk(self, doc: ParsedDocument) -> list[DocumentChunk]:
        return self._docling_chunks(doc)

    def _docling_chunks(self, document: ParsedDocument) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        for chunk in self._chunker.chunk(dl_doc=document.original_out_doc.raw):
            doc_chunk = DocChunk.model_validate(chunk)
            raw_text = self._chunk_text(doc_chunk)
            contextualized_text = self._contextualized_text(doc_chunk)
            text = contextualized_text or raw_text
            if not text:
                continue
            doc_items, page_numbers = _docling_chunk_refs(doc_chunk)
            chunk_index = len(chunks)
            chunks.append(
                self._document_chunk(
                    document=document,
                    chunk_index=chunk_index,
                    content=text,
                    raw_text=raw_text,
                    content_token_count=self._count_tokens(text),
                    doc_items=doc_items,
                    page_numbers=page_numbers,
                )
            )
        return chunks

    @staticmethod
    def _chunk_text(chunk: DocChunk) -> str:
        return chunk.text.strip()

    def _contextualized_text(self, chunk: DocChunk) -> str:
        return self._chunker.contextualize(chunk=chunk).strip()

    def _count_tokens(self, text: str) -> int | None:
        return self._chunker.tokenizer.count_tokens(text)

    def _document_chunk(
        self,
        *,
        document: ParsedDocument,
        chunk_index: int,
        content: str,
        raw_text: str,
        content_token_count: int | None,
        doc_items: list[str],
        page_numbers: list[int],
    ) -> DocumentChunk:
        return DocumentChunk(
            content=content,
            document_id=document.document_id,
            chunk_id=f"{document.document_id}-{chunk_index:05d}",
            chunk_index=chunk_index,
            chunking_strategy=self.type,
            content_token_count=content_token_count,
            doc_items=doc_items,
            page_number=page_numbers[0] if page_numbers else None,
            page_numbers=page_numbers,
            total_pages=document.page_count,
            title=document.title,
            source_file_name=document.source_file_name,
            raw_text=raw_text,
        )
