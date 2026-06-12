import re
from functools import lru_cache
from typing import Any, cast

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
from metrics.progress import ProgressReporter
from model.document_chunk import DocumentChunk
from model.parsed_document import ParsedDocument
from model.title_normalization import normalize_document_title
from processing.base_chunker import AbstractChunker


_DECIMAL_NUMBER_RE = re.compile(r"\d+(?:\.\d{3})*,\d+")
_INTEGER_RE = re.compile(r"\d+")
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
SPARSE_CHUNK_MAX_TOKENS = 512
CHUNK_OVERLAP_TOKENS = 100
MARKDOWN_SINGLE_CHUNK_MAX_TOKENS = SPARSE_CHUNK_MAX_TOKENS
_MARKDOWN_INPUT_FORMATS = {"md", "markdown"}


def _docling_chunk_refs(chunk: DocChunk) -> tuple[list[str], list[int]]:
    doc_items = chunk.meta.doc_items
    item_refs = []
    pages = []
    for item in doc_items:
        item_refs.append(str(item.self_ref))
        for prov in item.prov:
            pages.append(prov.page_no)
    return list(dict.fromkeys(item_refs)), sorted(set(pages))


def _docling_chunk_headings(chunk: DocChunk) -> list[str]:
    headings = chunk.meta.headings or []
    normalized_headings = []
    seen = set()
    for heading in headings:
        value = str(heading).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized_headings.append(value)
    return normalized_headings


def _markdown_headings(markdown: str) -> list[str]:
    headings = []
    seen = set()
    for line in markdown.splitlines():
        match = _MARKDOWN_HEADING_RE.match(line)
        if not match:
            continue
        heading = " ".join(match.group(1).split()).strip()
        if not heading or heading in seen:
            continue
        seen.add(heading)
        headings.append(heading)
    return headings


def _docling_metadata(document: ParsedDocument) -> dict[str, Any]:
    metadata = document.metadata.get("docling", {})
    if isinstance(metadata, dict):
        return metadata
    return {}


def _is_markdown_like_unpaged_document(document: ParsedDocument) -> bool:
    if document.page_count > 0:
        return False

    metadata = _docling_metadata(document)
    input_format = str(metadata.get("input_format") or "").lower()
    preprocessed_format = str(metadata.get("preprocessed_format") or "").lower()
    return (
        input_format in _MARKDOWN_INPUT_FORMATS
        or preprocessed_format in _MARKDOWN_INPUT_FORMATS
    )


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
    _max_tokens: int = PrivateAttr(default=SPARSE_CHUNK_MAX_TOKENS)
    _chunk_overlap_tokens: int = PrivateAttr(default=CHUNK_OVERLAP_TOKENS)

    def __init__(
        self,
        server_config: ServerConfig,
        tokenizer_path: str,
        type_: str | None = None,
        **data: Any,
    ) -> None:
        chunk_type = type_ or str(data.pop("type"))
        super().__init__(
            type=chunk_type,
            server_config=server_config,
        )

        if chunk_type != "token":
            raise ValueError(f"Unsupported Docling chunk type: {chunk_type}")
        if server_config.chunk_max_tokens <= 0:
            raise ValueError("chunk_max_tokens must be greater than zero")

        self._max_tokens = min(server_config.chunk_max_tokens, SPARSE_CHUNK_MAX_TOKENS)
        self._chunk_overlap_tokens = min(
            CHUNK_OVERLAP_TOKENS,
            max(0, self._max_tokens - 1),
        )
        self._chunker = self._build_token_chunker(
            tokenizer_path=str(tokenizer_path),
            max_tokens=self._max_tokens,
        )

    @staticmethod
    @lru_cache(maxsize=8)
    def _build_token_chunker(tokenizer_path: str, max_tokens: int) -> HybridChunker:
        from_pretrained = cast(Any, AutoTokenizer.from_pretrained)
        tokenizer = from_pretrained(
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

    def chunk(
        self,
        doc: ParsedDocument,
        progress: ProgressReporter,
    ) -> list[DocumentChunk]:
        chunks = self._docling_chunks(doc)
        progress.chunks_created(len(chunks))
        return chunks

    def _docling_chunks(self, document: ParsedDocument) -> list[DocumentChunk]:
        single_chunk = self._markdown_single_chunk_if_small(document)
        if single_chunk is not None:
            return single_chunk

        chunks: list[DocumentChunk] = []
        for chunk in self._chunker.chunk(dl_doc=document.original_out_doc.raw):
            doc_chunk = DocChunk.model_validate(chunk)
            base_text = self._chunk_text(doc_chunk)
            contextualized_text = self._contextualized_text(doc_chunk)
            content = contextualized_text or base_text
            if not content:
                continue
            doc_items, page_numbers = _docling_chunk_refs(doc_chunk)
            headings = _docling_chunk_headings(doc_chunk)
            for chunk_content in self._split_content_to_sparse_limit(content):
                chunk_index = len(chunks)
                chunks.append(
                    self._document_chunk(
                        document=document,
                        chunk_index=chunk_index,
                        content=chunk_content,
                        content_token_count=self._count_tokens(chunk_content),
                        doc_items=doc_items,
                        page_numbers=page_numbers,
                        headings=headings,
                    )
                )
        return chunks

    def _markdown_single_chunk_if_small(
        self,
        document: ParsedDocument,
    ) -> list[DocumentChunk] | None:
        if not _is_markdown_like_unpaged_document(document):
            return None

        content = self._markdown_content(document)
        if not content:
            return []

        content_token_count = self._count_tokens(content)
        if (
            content_token_count is None
            or content_token_count > MARKDOWN_SINGLE_CHUNK_MAX_TOKENS
        ):
            return None

        return [
            self._document_chunk(
                document=document,
                chunk_index=0,
                content=content,
                content_token_count=content_token_count,
                doc_items=[],
                page_numbers=[],
                headings=_markdown_headings(content),
            )
        ]

    @staticmethod
    def _markdown_content(document: ParsedDocument) -> str:
        if document.markdown.strip():
            return document.markdown.strip()
        return document.get_markdown().strip()

    @staticmethod
    def _chunk_text(chunk: DocChunk) -> str:
        return chunk.text.strip()

    def _contextualized_text(self, chunk: DocChunk) -> str:
        return self._chunker.contextualize(chunk=chunk).strip()

    def _count_tokens(self, content: str) -> int | None:
        return self._chunker.tokenizer.count_tokens(content)

    def _within_sparse_limit(self, content: str) -> bool:
        token_count = self._count_tokens(content)
        return token_count is not None and token_count <= self._max_tokens

    def _split_content_to_sparse_limit(self, content: str) -> list[str]:
        stripped = content.strip()
        if not stripped:
            return []
        if self._within_sparse_limit(stripped):
            return [stripped]
        return [chunk for chunk in self._tokenizer_chunks(stripped) if chunk.strip()]

    def _tokenizer_chunks(self, content: str) -> list[str]:
        tokenizer = getattr(self._chunker.tokenizer, "get_tokenizer", lambda: None)()
        encode = getattr(tokenizer, "encode", None)
        decode = getattr(tokenizer, "decode", None)
        if callable(encode) and callable(decode):
            token_ids = encode(content, add_special_tokens=False)
            if token_ids:
                chunks = []
                step = self._token_window_step()
                for start in range(0, len(token_ids), step):
                    decoded = decode(
                        token_ids[start : start + self._max_tokens],
                        skip_special_tokens=True,
                    ).strip()
                    if decoded:
                        chunks.append(decoded)
                if chunks:
                    return chunks

        return self._word_chunks(content)

    def _token_window_step(self) -> int:
        return max(1, self._max_tokens - self._chunk_overlap_tokens)

    def _word_chunks(self, content: str) -> list[str]:
        words = content.split()
        if not words:
            return []
        step = self._token_window_step()
        return [
            " ".join(words[start : start + self._max_tokens])
            for start in range(0, len(words), step)
        ]

    def _document_chunk(
        self,
        *,
        document: ParsedDocument,
        chunk_index: int,
        content: str,
        content_token_count: int | None,
        doc_items: list[str],
        page_numbers: list[int],
        headings: list[str],
    ) -> DocumentChunk:
        clean_title = normalize_document_title(
            document.title,
            strip_extension=True,
        ) or normalize_document_title(
            document.source_file_name,
            strip_extension=True,
        )
        return DocumentChunk(
            content=content,
            content_sparse=content,
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
            clean_title=clean_title,
            headings=headings,
            source_file_name=document.source_file_name,
        )
