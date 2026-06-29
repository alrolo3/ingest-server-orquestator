---
name: elastic-rag-agent
description: Create, update, or audit Elasticsearch and Kibana grounded RAG agent prompts and workflow YAML for this ingest-server-orquestator repository, including rag-AGENT instructions, rag-workflow retrieval logic, multilingual RRF search, query rewrite prompts, retrieval retry and reformulation behavior, critical-keyword preservation, citations, and insufficient-evidence handling over open-rag-embeddings-v4. Use when Codex needs to improve Elastic Agent Builder RAG behavior or document the current RAG workflow.
---

# Elastic RAG Agent

## Required Context

Load the references before changing agent prompts or workflow YAML:

- Read `references/current-rag-workflow.md` for the runtime index, ingest pipeline, retrieval fields, and workflow contracts.
- Read `references/agent-instruction-template.md` when editing `elastic_integration/rag-AGENT.md` or creating new Agent Builder instructions.
- Inspect the checked-in source artifacts before editing them: `elastic_integration/rag-AGENT.md`, `elastic_integration/rag-workflow.yml`, and `docs/ingest-server-pipeline-workflow.md`.

Treat `elastic_integration/rag-workflow.yml` as the current v4 workflow template. Treat `elastic_integration/rag-workflow-v2.yml` as older semantic-only context unless the user explicitly asks for v2.

## Workflow

1. Identify the target artifact: agent instructions, workflow YAML, operational docs, or an answer explaining RAG behavior.
2. Preserve the grounding contract: answers must use returned `documents` as evidence, not outside knowledge, and must cite source filename, page, chunk, and heading/context.
3. Preserve the index contract: user-visible evidence text belongs in `_source.content`; generated `content_dense` and `content_sparse` fields exist for retrieval and may be excluded from `_source`.
4. Preserve the workflow contract: first-stage retrieval uses conversation-aware rewrite, dense and sparse semantic branches, sparse title and heading branches, RRF, then same-page and neighboring-page expansion.
5. Add or maintain an explicit evidence gate after retrieval. The agent must inspect whether returned chunks actually answer the question before synthesizing.
6. Add or maintain retrieval retry behavior. When first retrieval is empty, irrelevant, or misses a named document/topic, the agent should call the retrieval tool again with a reformulated question that keeps all critical keywords unchanged.
7. Keep final answers concise and grounded. Do not expose hidden reasoning, search diagnostics, or internal retry details unless the user asks for troubleshooting.

## Retrieval Reasoning Contract

Use this hidden planning pattern when writing agent instructions:

- Extract critical keywords before the first retrieval. Critical keywords include exact document names, filenames, IDs, model names, product names, legal or rule references, page hints, section names, acronyms, numbers, dates, named entities, quoted phrases, table labels, and domain-specific Spanish or English terms.
- Keep critical keywords unchanged across every query. Do not translate, drop, singularize, pluralize, or paraphrase them unless the query also keeps the original form.
- Use the first retrieval call with the user question exactly as written and compact `conversation_context` only when a follow-up needs prior context.
- Evaluate the returned `documents`, not just scores. Good evidence must contain the requested entity or topic and enough content to answer.
- If evidence is weak, retry with a reformulated retrieval question. Remove chat filler, resolve pronouns, add likely headings or synonyms, and add English or Spanish variants, but preserve the critical keywords exactly.
- Prefer one narrow retry and one broader retry. Stop after two unsuccessful reformulations unless the user provides a new clue.
- If retries still do not produce evidence, say the available documents do not provide enough information. Do not fabricate facts, citations, page numbers, or filenames.

Example reformulation behavior:

```text
Original question:
What does AC_35-D_1042 say about ZAR zones I and II?

Critical keywords to preserve:
AC_35-D_1042, ZAR, I, II

Retry question if first retrieval misses the document:
AC_35-D_1042 ZAR zones I II requirements exceptions criteria
```

## Agent Update Checklist

When editing `rag-AGENT.md`, ensure it says:

- Call `rag_query_tool` for knowledge-base questions.
- Pass the latest user question exactly as `question`.
- Pass only compact prior-turn context as `conversation_context`.
- Read `documents` first; use `initial_rrf_documents` only for diagnostics.
- Run the evidence gate before answering.
- Retry retrieval by reformulating when returned chunks are missing the answer or missing locked critical keywords.
- Preserve exact critical keywords during reformulation.
- Answer only from returned passages.
- Include a references section even when evidence is insufficient.

## Workflow Update Checklist

When editing `rag-workflow.yml`, ensure it keeps:

- Index `open-rag-embeddings-v4`.
- Filters `record_type: chunk`, `searchable: true`, and `boilerplate: false`.
- Returned `_source.content` for visible grounding text.
- `question_original`, `standalone_question`, and `answer_language` from the rewrite step.
- RRF over dense `content_dense`, sparse `content_sparse`, sparse `clean_title`, and sparse `headings` branches.
- Page expansion by `document_id` plus `page_number` and `page_numbers`, with legacy `page_start`/`page_end` only as fallback when present.
- Final output fields `documents`, `initial_rrf_documents`, `retrieval_strategy`, and `instruction`.

## References

- `references/current-rag-workflow.md`: current ingest, index, and retrieval workflow summary.
- `references/agent-instruction-template.md`: reusable grounded RAG agent instruction template with retry/reformulation behavior.
