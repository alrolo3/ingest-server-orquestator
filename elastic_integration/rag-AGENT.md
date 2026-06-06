# Grounded RAG Q&A

  ## When to Use This Skill

  Use this skill when the user asks a question that should be answered from the indexed knowledge base, including:

  - Questions about documents, policies, rules, manuals, procedures, reports, books, PDFs, internal notes, or indexed content.
  - Requests such as “answer from my docs”, “what does the document say”, “summarize this topic”, “explain this section”, or “where is this stated”.
  - Multi-turn follow-ups such as “what about the second one?”, “explain that”, “and in Spanish?”, “what does it say about X?”, or “compare it with the previous rule”.
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

  ## Required Process

  1. For any knowledge-base question, call `rag_query_tool` before answering.
  2. Set `question` to the latest user question exactly.
  3. Set `conversation_context` to a short summary of only the previous turns needed to resolve the current question.
     - Include previous subjects, entities, document names, section names, rules, options, or answer fragments that the user refers to.
     - Do not include unrelated conversation.
     - Use an empty string if the current question is already standalone.
  4. Read the returned `documents`.
  5. Answer using only information contained in `documents`.
  6. If the documents do not contain enough information to answer confidently, say that the available documents do not provide enough information.
  7. Do not invent facts, assumptions, citations, URLs, page numbers, document titles, or details that are not present in the retrieved documents.
  8. If multiple documents are relevant, synthesize them into a clear answer.
  9. When useful, cite or reference the supporting document title, clean title, source file name, and page range.
  10. Answer in `answer_language` unless the user explicitly asks for another language.

  ## Multi-Turn Query Handling

  For follow-up questions, the tool must receive enough context to rebuild the query.

  Good `conversation_context` examples:

  - `Previous topic: refund policy. The user asked about deadlines and exceptions.`
  - `Previous answer discussed Prismatic Wall layers. User is now asking about destroying the second layer.`
  - `Previous document: AC_35-D_1042. User asked about ZAR zones I and II.`
  - `Previous comparison: Docling vs MinerU. User now asks which one handles tables better.`

  Bad `conversation_context` examples:

  - Full transcript dump when only one entity matters.
  - Irrelevant user preferences.
  - Hidden reasoning.
  - Tool output copied wholesale unless needed.

  ## Grounding Rules

  - Treat retrieved documents as the only source of truth.
  - Do not use outside knowledge to fill gaps.
  - Do not claim a source says something unless that information appears in the returned documents.
  - If documents conflict, explain the conflict and identify which document or passage supports each side.
  - If retrieved passages are only partially relevant, give the partial answer and clearly state what is missing.
  - If no documents are returned, say that the available documents do not provide enough information.

  ## Response Style

  - Be concise, direct, and professional.
  - Prefer short paragraphs.
  - Use bullets for lists, procedures, requirements, or comparisons.
  - Do not expose internal reasoning.
  - Do not mention the tool unless it helps explain that the answer is based on retrieved documents.
  - Include source references naturally, for example:
    - `According to <title>, page <page_start>-<page_end>...`
    - `The retrieved passage from <source_file_name> states...`
    - `The available documents only show...`

  ## Example

  User asks:

  “What is our refund policy?”

  Tool call:

  ```json
  {
    "question": "What is our refund policy?",
    "conversation_context": ""
  }
   ```
Then answer only from the returned documents.

Follow-up example:

User previously asked about refund policy deadlines.

User asks:

“And what are the exceptions?”

Tool call:
```json
{
  "question": "And what are the exceptions?",
  "conversation_context": "Previous topic: refund policy deadlines. The user is asking for exceptions to the refund policy."
}
   ```
Then answer only from the returned documents.