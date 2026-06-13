# Current Elastic RAG Workflow

Use this reference when updating RAG agent instructions, workflow YAML, or docs for this repository.

## Runtime Names

| Item | Current value |
| --- | --- |
| Index | `open-rag-embeddings-v4` |
| Ingest pipeline | `open_rag_embeddings_v4_multilingual_semantic_pipeline` |
| Kibana workflow ID | `rag-query-retrieval-tool-v4-conversation-aware` |
| Workflow template | `elastic_integration/rag-workflow.yml` |
| Agent template | `elastic_integration/rag-AGENT.md` |
| Older workflow context | `elastic_integration/rag-workflow-v2.yml` |
| Result size | `10` |
| Expansion size | `30` |

## Ingest And Source Contract

The indexed `DocumentChunk` keeps user-visible text in `_source.content`. This is required because the user needs to see the plain text evidence in returned documents.

Generated retrieval fields are derived from `content`:

- `content_dense`: dense `semantic_text` search field using endpoint `openai-text_embedding-qwen3-embedding-4b`; excluded from `_source`.
- `content_sparse`: sparse `semantic_text` search field using endpoint `naver-splade-v3`; excluded from `_source`.
- `content_lex.en`, `content_lex.es`, `content_lex.fr`: language-routed lexical fields for BM25-style retrieval; excluded from `_source`.
- `clean_title`: sanitized title used for sparse title retrieval and returned in `_source`.
- `headings`: Docling heading hierarchy used for sparse heading retrieval and returned in `_source`.

Do not remove `_source.content` from retrieval output. The agent cannot ground answers if only generated search fields are returned.

## Chunking Context

The current Docling chunker:

- Uses Docling `HybridChunker` with the Qwen3 tokenizer from `/tokenizer`.
- Caps token chunks at `512` tokens for sparse inference stability.
- Emits Markdown-like documents without pages as one chunk when the full exported Markdown is at or below `512` tokens.
- Repeats table headers across split table chunks.
- Uses contextualized chunk text where available.
- Splits oversized contextualized chunks into token windows with `100` token overlap.
- Coalesces adjacent chunks below `128` tokenizer tokens when the merged chunk still fits under the `512` token cap.
- Keeps page provenance in `page_number`, `page_numbers`, `page_start`, and `page_end`.

Some short chunks can remain when they cannot be safely merged without crossing document item, page, or token-budget boundaries.

## Ingest Pipeline Contract

The ingest pipeline normalizes chunk metadata before semantic indexing:

- Set `record_type=chunk`.
- Normalize `clean_title` and `headings`.
- Populate `content_dense` and `content_sparse` from `content`.
- Set `content_length`, `searchable=true`, `boilerplate=false`, and `content_kind=chunk`.
- Run `lang_ident_model_1` over `content`.
- Route lexical text into `content_lex.es`, `content_lex.en`, or `content_lex.fr`; default to English for unsupported or low-confidence language detection.
- Keep returned evidence fields in `_source`: `content`, `title`, `clean_title`, `headings`, `source_file_name`, page fields, chunk IDs, and document IDs.

Automatic Elasticsearch semantic chunking is disabled because the application pre-chunks documents before indexing.

## Workflow Inputs And Rewrite Output

The RAG workflow receives:

- `question`: latest user question exactly as written.
- `conversation_context`: compact prior-turn context needed to resolve follow-ups, or an empty string.

The rewrite step must produce:

- `question_original`: exact current user question.
- `standalone_question`: self-contained retrieval query.
- `query_en`: English lexical/search variant.
- `query_es`: Spanish lexical/search variant.
- `answer_language`: `en` or `es`, usually matching the current user question.

The rewrite step must not answer the question, introduce unsupported assumptions, or drop exact identifiers from the current question or conversation context.

## First-Stage Retrieval

The current workflow uses RRF with filters:

- `record_type: chunk`
- `searchable: true`
- `boilerplate: false`

Branches include:

| Branch | Query text | Fields |
| --- | --- | --- |
| Standalone lexical | `standalone_question` | `content_lex.*`, `title`, `source_file_name.text` |
| Original lexical | `question_original` | `content_lex.*`, `title`, `source_file_name.text` |
| English lexical | `query_en` | `content_lex.en`, `title`, `source_file_name.text` |
| Spanish lexical | `query_es` | `content_lex.es`, `title`, `source_file_name.text` |
| Dense content semantic | `standalone_question` | `content_dense` |
| Sparse content semantic | `standalone_question` | `content_sparse` |
| Sparse title semantic | all rewrite variants | `clean_title` |
| Sparse heading semantic | all rewrite variants | `headings` |

Language variants improve recall; they must not be used as hard document-language filters.

## Context Expansion

After first-stage retrieval, the workflow expands context around the seed hits:

- Keep first-stage seed hits.
- Search the same `document_id`.
- Include chunks on the same page, previous page, and next page.
- Use `page_number`, `page_numbers`, `page_start`, and `page_end` when available.
- Return expanded hits as `documents`.
- Return first-stage mapped hits as `initial_rrf_documents` for diagnostics only.

The agent should answer from `documents`. It should use `initial_rrf_documents` only to debug retrieval behavior or explain why expansion failed.

## Agent Evidence Gate

The agent must check whether `documents` actually contain the answer before responding.

Good evidence:

- Mentions the requested entity, document, section, or topic.
- Contains enough text in `content` to support the answer.
- Provides page or chunk metadata for references.

Weak evidence:

- Only matches generic words from the question.
- Does not contain the named document, filename, ID, or domain term requested.
- Contains a title match but no answer content.
- Conflicts with other retrieved passages without enough context to resolve the conflict.

When evidence is weak, the agent should retry retrieval with a better query rather than immediately answer "not found".

## Retry And Reformulation Policy

The retry policy belongs in the agent instructions because the current workflow performs one retrieval pass per tool call.

On the first retrieval failure:

1. Identify locked critical keywords from the user question and needed conversation context.
2. Keep locked keywords exactly as written in every retry.
3. Reformulate by removing filler, resolving pronouns, adding likely headings, adding synonyms, and adding English or Spanish equivalents.
4. Call `rag_query_tool` again with the reformulated `question`.
5. Use compact `conversation_context` only when needed.

Recommended retry shape:

- Retry 1: narrow query with exact identifiers plus likely section/table terms.
- Retry 2: broader query with exact identifiers plus synonyms or bilingual terms.

Stop after two unsuccessful retries unless the user supplies a new clue. Then answer that the available documents do not provide enough information.

Critical keywords include exact filenames, IDs, model names, acronyms, page hints, dates, numbers, legal/rule references, proper nouns, quoted phrases, table labels, and domain-specific terms such as `ZAR`.

## Reference Contract

Every answer must finish with references. Each reference should include, in order:

1. `source_file_name` or filename unknown.
2. Page value from `page_start`/`page_end`, else `page_number`, else `page_numbers`, else page unknown.
3. `chunk_id` or ID unknown.
4. `headings` or a short grounded context phrase.

Do not infer page numbers, filenames, or headings from chunk order.
