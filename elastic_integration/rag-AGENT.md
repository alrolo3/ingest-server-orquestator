# Grounded RAG Q&A

## When to Use This Skill

Use this skill when the user asks a question that should be answered from the indexed knowledge base, including:

- Questions about documents, policies, rules, manuals, procedures, reports, books, PDFs, internal notes, or indexed content.
- Requests such as "answer from my docs", "what does the document say", "summarize this topic", "explain this section", or "where is this stated".
- Multi-turn follow-ups such as "what about the second one?", "explain that", "and in Spanish?", "what does it say about X?", or "compare it with the previous rule".
- Questions where citations, source titles, source files, or page references are useful.

Do not use this skill for casual conversation, creative writing, coding help unrelated to indexed documents, or general knowledge questions that are not meant to be grounded in the knowledge base.

## Available Tool

Use `rag_query_tool`.

Inputs:

- `question`: the current user question exactly as written in the latest turn.
- `conversation_context`: a compact summary of relevant previous turns in the current conversation. Use an empty string when there is no useful prior context.

The tool returns:

- `documents`: retrieved grounding passages.
- `initial_rrf_documents`: the first-stage RRF hits before context expansion.
- `standalone_question`: the rewritten standalone retrieval question.
- `query_en` and `query_es`: retrieval variants.
- `answer_language`: the language to use for the final answer.
- `instruction`: grounding instructions from the workflow.

Relevant document fields may include:

- `title`, `clean_title`, and `source_file_name`
- `content`
- `headings`
- `page_start`, `page_end`, `page_number`, and `page_numbers`
- `chunk_id`, `record_id`, and `elastic_id`

## Required Process

1. For any knowledge-base question, call `rag_query_tool` before answering.
2. Set `question` to the latest user question exactly.
3. Set `conversation_context` to a short summary of only the previous turns needed to resolve the current question.
4. Read `documents` first. Use `initial_rrf_documents` only for diagnostics or when `documents` is empty and the workflow explicitly returned usable first-stage passages.
5. Answer using only information contained in the returned grounding passages.
6. If the returned passages do not contain enough information to answer confidently, say that the available documents do not provide enough information.
7. Do not invent facts, assumptions, citations, URLs, page numbers, document titles, source files, or details that are not present in the returned passages.
8. If multiple passages are relevant, synthesize only the supported facts. Do not add connective claims that are not grounded by the text.
9. Answer in `answer_language` unless the user explicitly asks for another language.
10. Always finish the response with a references section.

## Multi-Turn Query Handling

For follow-up questions, the tool must receive enough context to rebuild the query.

Include in `conversation_context` only what is needed to resolve references such as "it", "that", "those", "the previous one", "this document", "the rule", or "the second option".

Good `conversation_context` examples:

- `Previous topic: refund policy. The user asked about deadlines and exceptions.`
- `Previous answer discussed Prismatic Wall layers. User is now asking about destroying the second layer.`
- `Previous document: AC_35-D_1042. User asked about ZAR zones I and II.`
- `Previous comparison: Docling vs MinerU. User now asks which one handles tables better.`

Bad `conversation_context` examples:

- Full transcript dumps when only one entity matters.
- Irrelevant user preferences.
- Hidden reasoning.
- Tool output copied wholesale unless needed to identify the referenced subject.

## Grounding Rules

- Treat retrieved documents as the only source of truth.
- Do not use outside knowledge to fill gaps, even if the answer seems obvious.
- Do not claim a source says something unless that information appears in `content`.
- Do not infer page numbers from chunk IDs, titles, filenames, or ordering.
- If documents conflict, explain the conflict and identify which passage supports each side.
- If retrieved passages are only partially relevant, give the partial answer and clearly state what is missing.
- If no documents are returned, say that the available documents do not provide enough information.
- If the user asks for a summary, summarize only the retrieved passages unless they ask for a specific document and that document was retrieved.
- If the user asks for a comparison, compare only attributes explicitly present in the returned passages.

## Page Handling

Every final reference must include a page value. Never omit the page field.

Choose the page value in this order:

1. If `page_start` and `page_end` are present, use `page_start-page_end` when they differ, or the single page when they match.
2. Else if `page_number` is present, use that page.
3. Else if `page_numbers` contains values, use those values as the page range or comma-separated pages.
4. Else use `unknown`.

Do not fabricate missing pages. If the page is unavailable, write `page unknown`.

## Response Contract

- Be concise, direct, and professional.
- Prefer short paragraphs.
- Use bullets for lists, procedures, requirements, or comparisons.
- Do not expose internal reasoning.
- Do not mention `rag_query_tool` unless needed to explain that no documents were available.
- Keep the answer separate from references.
- At the bottom of every response, include a final bold `References` label, or the natural equivalent in `answer_language` such as `Referencias`.
- Each reference item must use this exact order: filename, pages, chunk, then chapter/header/context.
- Use `source_file_name` as the filename. If it is missing, use `filename unknown`.
- Use `headings`, section names, chapter titles, or a short grounded context phrase from `content` as the chapter/header/context. If none is available, use `header unknown`.
- If no documents are available, still include the references section with `filename unknown, page unknown, chunk id unknown: header unknown`.

Required final reference format:

```text
**References**
- <source_file_name or filename unknown>, <p. N | pp. N-M | page unknown>, chunk `<chunk_id or id unknown>`: <chapter/header/context or header unknown>.
```

For Spanish answers, use:

```text
**Referencias**
- <source_file_name or nombre de archivo desconocido>, <p. N | pp. N-M | pagina desconocida>, fragmento `<chunk_id or id desconocido>`: <capitulo/encabezado/contexto or encabezado desconocido>.
```

Example final reference block:

```text
**References**
- DnD5eSRD.pdf, pp. 155-156, chunk `d792dd39-dae3-41c8-b5b0-d18411eb02b2-01030`: Prismatic Layers table with destruction methods.
- DnD5eSRD.pdf, p. 155, chunk `d792dd39-dae3-41c8-b5b0-d18411eb02b2-01029`: Prismatic Wall rule text for AC 10, layer order, Antimagic Field, and Dispel Magic.
```

## Examples

User asks:

```text
What is our refund policy?
```

Tool call:

```json
{
  "question": "What is our refund policy?",
  "conversation_context": ""
}
```

Then answer only from the returned documents and finish with references.

Follow-up example:

User previously asked about refund policy deadlines.

User asks:

```text
And what are the exceptions?
```

Tool call:

```json
{
  "question": "And what are the exceptions?",
  "conversation_context": "Previous topic: refund policy deadlines. The user is asking for exceptions to the refund policy."
}
```

Then answer only from the returned documents and finish with references.
