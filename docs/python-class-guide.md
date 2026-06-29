# Guia de clases Python del ingest server

Este documento baja a nivel de clase para que un dev nuevo entienda como fluye
un documento desde la entrada del API o carpeta compartida hasta Elasticsearch.
El alcance principal es `src/ingest-server-orquestator`, que contiene el codigo
productivo. Las clases de `tests/` aparecen al final como mapa de cobertura.

Para el flujo completo de despliegue y RAG, leer tambien:

- `docs/ingest-server-pipeline-workflow.md`
- `docs/ingest-server-kubernetes-architecture.md`
- `docs/k3s-airgapped-deployment.md`

## Flujo operativo

1. El API o el scanner de carpeta compartida crea un `Job`.
2. El `Job` se registra en `JobMetricsStore` y entra en `local_queue`.
3. `InboundWorker` consume la cola y ejecuta `job_runner` en un proceso hijo.
4. `job_runner` carga `ServerConfig`, configura CUDA/Torch y crea un
   `ProgressReporter`.
5. `DoclingParser` convierte PDF, Markdown, JSON y formatos Docling soportados
   a `ParsedDocument`.
6. `DoclingChunker` transforma el `ParsedDocument` en `DocumentChunk` ya
   limitado para los campos `semantic_text` de Elasticsearch.
7. `job_runner` escribe el Markdown y los JSON de chunks en disco.
8. `ElasticsearchDispatch` asegura pipeline/indice y hace bulk indexing.
9. `ProgressReporter` marca tiempos, contador de paginas/chunks, output y
   estado final.
10. Si el trabajo venia de carpeta compartida, `update_shared_ingest_state`
    actualiza `.ingest-state.json`.

## Configuracion

### `config.config.ServerConfig`

Contrato inmutable de configuracion runtime. Es un `dataclass(frozen=True,
slots=True)` cargado una vez desde variables de entorno mediante
`load_server_config()` / `get_server_config()`.

Responsabilidades:

- Define valores de servicio: nombre de app, entorno, cola inbound y cantidad
  de workers.
- Define recursos locales: tokenizer, artefactos Docling, layout model, modelo
  MinerU y carpeta compartida.
- Define CUDA/Docling: device visible, device logico, OCR engine, lenguajes,
  batch sizes, tabla, layout, enriquecimiento de imagen/codigo/formula y timeouts.
- Define Elasticsearch: hosts, API key, indice, pipeline, inference IDs, TLS,
  compresion y parametros de bulk.
- Define shared ingest: habilitado, carpeta raiz, intervalo de scan y segundos
  de estabilidad antes de encolar un archivo.

Detalles de comportamiento:

- `ELASTIC_URL` sirve como fallback de un solo host si no se define
  `ELASTIC_HOSTS`.
- Los enteros/batches con minimo operativo se normalizan con `max(...)`.
- `DOCLING_TABLE_MODE` se valida contra `accurate` y `fast`.
- El OCR `rapidocr` cambia el default de idioma a `english`; `auto` usa lista
  vacia para que Docling decida.
- La instancia queda cacheada en `_SERVER_CONFIG`; cambiar env vars despues de
  cargarla no cambia el runtime salvo que el proceso reinicie.

## Modelo de trabajo y metricas

### `queues.domain.job.Job`

Payload de cola para un ingest individual.

Campos principales:

- `job_id`: UUID generado por `Job.create`.
- `parser_type`: hoy se espera `docling`.
- `chunker_type`: hoy se espera `token`.
- `input_data`: metadata de entrada. Normalmente incluye `file_path`,
  `file_name`, `mime_type`, `size_bytes`, `collection_name`, `task_id` y
  `document_metadata`.
- `settings`: overrides operativos, por ejemplo `elastic_index_name`.
- `status` y `created_at`: estado inicial y timestamp UTC.

Metodos:

- `create(...)`: genera UUID y aplica `settings or {}`.
- `to_queue_message()`: serializa el job a dict para inspeccion/debug.

### `metrics.job_metrics.JobStage`

Enum fino de fase interna: `queued`, `running`, `parsing`, `chunking`,
`dispatching`, `outputting`, `done`, `failed`.

Se usa para mostrar en que parte concreta esta el pipeline y para ubicar fallos.

### `metrics.job_metrics.JobStatus`

Enum grueso para consumidores externos: `queued`, `running`, `done`, `failed`.

`stage_status(stage)` convierte fases internas a este estado simplificado:
`queued`, `done` y `failed` conservan su estado; todo lo demas es `running`.

### `metrics.job_metrics.JobMetrics`

Snapshot serializable de progreso.

Agrupa:

- Identidad: job, archivo, origen, parser, chunker.
- Estado: `status`, `stage`, `message`, `error`.
- Contadores: paginas, chunks creados, chunks enviados.
- Tiempos: total, parse, chunk, dispatch, timings por etapa y etapa mas lenta.
- Tasas calculadas: paginas/segundo, chunks/segundo, dispatch chunks/segundo.
- Salida: nombre, path y URL del Markdown generado.
- Timestamps: creado, iniciado, actualizado, finalizado.

Metodos:

- `queued(...)`: crea el registro inicial en estado `queued`.
- `to_dict()`: devuelve dict mutable para store/API.

### `metrics.store.JobMetricsStore`

Fachada sobre un `MutableMapping`. Puede usar un dict local o un mapping de
`multiprocessing.Manager`, por eso sirve entre proceso API y workers.

Metodos:

- `create_for_job(job)`: crea el registro inicial a partir del `Job`.
- `ensure_job(job)`: devuelve el registro existente o lo crea.
- `get(job_id)`: devuelve copia del registro o `None`.
- `list(status=None, stage=None, limit=None)`: filtra, ordena por `created_at`
  descendente y limita resultados.
- `mark_stage(job_id, stage, message=None)`: actualiza fase y estado grueso;
  rellena `started_at` cuando entra en running.
- `update(job_id, **changes)`: upsert generico. Si no existe registro, crea un
  esqueleto running para no perder progreso.
- `mark_done(...)`: fija estado final exitoso y limpia error.
- `mark_failed(...)`: fija estado final fallido y registra error.

### `metrics.progress.ProgressReporter`

API pequena para que parser, chunker y dispatcher no conozcan la estructura de
`JobMetricsStore`.

Metodos:

- `mark_stage`: cambia fase y mensaje.
- `set_total_pages`: fija total de paginas, aceptando `None`.
- `page_processed`: incrementa paginas procesadas y opcionalmente genera mensaje.
- `chunks_created` / `chunks_dispatched`: actualizan contadores.
- `set_output`: guarda Markdown generado y URL publica.
- `record_timing`: normaliza segundos, guarda timings por etapa, calcula etapa
  mas lenta y tasas derivadas.
- `mark_done` / `mark_failed`: cierre del job.

### `metrics.progress.NullProgressReporter`

Implementa la misma interfaz que `ProgressReporter`, pero todos los metodos son
no-op. Sirve cuando un caller necesita pasar un reporter pero no quiere persistir
metricas.

## Documentos normalizados

### `model.base_document.AbstractOutputDocument`

Wrapper Pydantic para conservar el documento nativo producido por un parser.
Tiene un campo:

- `raw`: objeto original del parser.

La idea es no perder capacidades nativas del parser mientras se pasa una forma
normalizada al resto del pipeline.

### `model.base_document.DoclingOutputDocument`

Especializacion de `AbstractOutputDocument` donde `raw` es un
`DoclingDocument`. Permite que el chunker y el writer llamen a metodos de
Docling como `export_to_markdown()`.

### `model.parsed_document.ParsedDocument`

Resultado normalizado del parser.

Campos importantes:

- `document_id`: se alinea con `job_id`.
- `source_file_name`, `source_path`, `mime_type`, `source_size_bytes`.
- `collection_name` y `task_id`: arrastran contexto de coleccion/frontend.
- `title`: titulo detectado por Docling o derivado del archivo.
- `page_count`: cantidad de paginas si el input es paginado.
- `markdown` y `text`: slots normalizados; en la practica Docling se exporta
  desde `original_out_doc`.
- `metadata`: metadata propia del documento mas subclave `docling`.
- `original_out_doc`: wrapper con el documento nativo.

Metodo:

- `get_markdown()`: exporta Markdown desde `original_out_doc.raw`.

### `model.document_chunk.DocumentChunk`

Registro RAG ya pre-chunkeado que se indexa en Elasticsearch.

Campos de contenido:

- `content`: texto canonico guardado en `_source`.
- `content_dense`: texto para campo dense `semantic_text`; normalmente lo rellena
  el pipeline de Elasticsearch desde `content`.
- `content_sparse`: texto para campo sparse `semantic_text`; el chunker lo limita
  a 512 tokens.

Campos de identidad:

- `document_id`, `chunk_id`, `chunk_index`, `chunking_strategy`.
- `collection_name`, `task_id`, `source_size_bytes`.

Campos de trazabilidad Docling:

- `doc_items`: referencias Docling (`self_ref`) incluidas en el chunk.
- `page_number`, `page_numbers`, `total_pages`.
- `headings`, `title`, `clean_title`, `source_file_name`.
- `document_metadata`: metadata de entrada; se guarda como objeto deshabilitado
  en mappings para recuperacion, no para busqueda.

## Parser y OCR

### `processing.parsers.json_markdown.JsonToMarkdownPreprocessor`

Convierte JSON arbitrario a Markdown antes de pasarlo a Docling como input MD.

Metodos publicos:

- `from_file(path, title=None)`: lee UTF-8, rechaza JSON no UTF-8 y delega en
  `from_text`.
- `from_text(raw, title="JSON document")`: parsea JSON, crea un `# titulo` y
  renderiza el valor raiz.

Proceso interno:

- Los objetos separan escalares y anidados: escalares como bullets; anidados
  como subsecciones.
- Los arrays de objetos se renderizan como tabla si todos los items son mappings
  y al menos uno tiene datos.
- Arrays mixtos o anidados se renderizan como secciones `Item N`.
- Escalares usan `null`, `true`, `false` y `str(value)`.
- Celdas de tabla escapan `|` y saltos de linea.
- El documento final termina con newline unico.

### `processing.parsers.docling_parser.DoclingParser`

Parser principal. Convierte PDF, Markdown, JSON, DOCX, PPTX, XLSX, HTML, EML e
imagenes a `ParsedDocument` usando Docling.

Campos:

- `type`: parser solicitado; el runner solo acepta `docling`.
- `server_config`: configuracion runtime.

Metodo:

- `parse(job, progress)`: valida input, arma opciones Docling, ejecuta conversion,
  registra timings y devuelve `ParsedDocument`.

Proceso detallado:

- Valida `job.input_data["file_path"]` y detecta formato por extension/MIME:
  PDF, Markdown, JSON, DOCX, PPTX, XLSX, HTML, EML e imagenes.
- JSON no va directo a Docling: primero se convierte a Markdown con
  `JsonToMarkdownPreprocessor`.
- MSG queda rechazado: la version instalada de Docling expone email como EML.
- Configura `ThreadedPdfPipelineOptions` con:
  - acelerador Docling (`docling_device`, threads),
  - servicios remotos habilitados para descripcion de imagen,
  - artifacts locales,
  - OCR segun `DOCLING_OCR_ENGINE`,
  - layout PPDocLayout v3,
  - table structure con modo `accurate` o `fast`,
  - batch sizes y queue size.
- Desactiva chart extraction porque el modelo Granite de Docling es incompatible
  con la API de generacion instalada.
- Habilita descripcion de imagen via endpoint OpenAI-compatible configurado.
- Usa `ProgressReportingStandardPdfPipeline` para reportar paginas durante PDF.
- Para formatos sin pipeline visual ajusta temporalmente
  `docling_settings.settings.artifacts_path` a `None` para no forzar artefactos
  de PDF.
- Registra timings perfilados por Docling como `docling_<stage>`.
- Extrae titulo desde un `DocItemLabel.TITLE`; si no existe, usa nombre de doc o
  archivo limpiado por `normalize_document_title`.

### `processing.parsers.docling_progress.ProgressReportingStandardPdfPipeline`

Subclase de `StandardPdfPipeline` que conserva el pipeline threaded de Docling,
pero reporta progreso por pagina.

Metodos relevantes:

- `_make_ocr_model(art_path)`: selecciona `MinerU`, `SuryaOcrModel` o el factory
  nativo de Docling segun `ocr_options`.
- `_build_document(conv_res)`: replica el build loop threaded de Docling,
  inicializa paginas esperadas, produce paginas en un thread, consume batches del
  output queue, marca paginas procesadas o fallidas y cierra stages.

Detalles:

- Usa `ContextVar` para que `docling_progress(progress)` pase el reporter al
  pipeline sin cambiar la firma de Docling.
- Si no hay paginas esperadas, marca fallo y total 0.
- Si el producer falla o el output queue termina antes, marca paginas faltantes
  como fallidas.
- Si hay timeout, marca las paginas pendientes con error de timeout.

### `processing.parsers.mineru_ocr_model.MinerUOcrOptions`

Opciones Docling para OCR MinerU.

Campos principales:

- `kind="mineru"`.
- `lang`, `model_path`, `device`, `dtype`, `scale`, `confidence`.
- `batch_size`: batch para `MinerUClient`.
- `image_analysis`: activa/desactiva analisis de imagen en `two_step_extract`.

### `processing.parsers.mineru_ocr_model.MinerU`

Adaptador OCR de Docling respaldado por MinerU via Transformers.

Proceso:

- Si `enabled=False`, devuelve las paginas sin tocar.
- Carga `MinerUClient`, `AutoProcessor` y `Qwen2VLForConditionalGeneration`.
- Valida/avisa si `model_path` no existe.
- Carga modelo con `dtype` y `device_map`.
- Parchea `max_position_embeddings` si el config lo expone dentro de
  `text_config`.
- Si el checkpoint no trae `lm_head.weight`, intenta atar output embeddings a
  input embeddings para evitar generacion aleatoria.
- Por cada pagina valida, obtiene rectangulos OCR de Docling, recorta imagen,
  ejecuta `two_step_extract`, convierte bloques de texto a `TextCell` y deja que
  Docling haga `post_process_cells`.

Metodos:

- `_device_map()`: devuelve `"auto"` o mapea todo el modelo al device configurado.
- `__call__(conv_res, page_batch)`: ejecuta OCR por pagina.
- `block_to_text_cell(...)`: acepta solo tipos de bloque de texto conocidos,
  valida bbox normalizada `[0, 1]` y convierte a coordenadas de pagina Docling.
- `get_options_type()`: registra `MinerUOcrOptions` para Docling.

### `processing.parsers.surya_ocr_model.SuryaOcrOptions`

Opciones Docling para Surya OCR 2.

Campos principales:

- `kind="surya"`.
- `lang`, `scale`, `confidence`.
- `inference_url`: obligatorio cuando Surya esta habilitado.
- `inference_backend`, `inference_parallel`, `keep_alive`.

### `processing.parsers.surya_ocr_model.SuryaOcrModel`

Adaptador OCR de Docling respaldado por Surya y un endpoint de inferencia
OpenAI-compatible.

Proceso:

- Si `enabled=False`, devuelve paginas sin tocar.
- Exige `DOCLING_SURYA_INFERENCE_URL`.
- Copia settings a variables de entorno y tambien al objeto `surya.settings`.
- Crea `SuryaInferenceManager` y `RecognitionPredictor`.
- Por cada rectangulo OCR de pagina, recorta imagen, llama predictor, convierte
  bloques a `TextCell` y ejecuta `post_process_cells`.

Metodos:

- `__call__(conv_res, page_batch)`: ejecuta OCR remoto/local por pagina.
- `block_to_text_cell(...)`: ignora bloques `skipped`/`error`, extrae texto desde
  `text` o HTML, acepta `bbox` o `polygon`, recorta bbox a la imagen y convierte
  a coordenadas Docling.
- `get_options_type()`: registra `SuryaOcrOptions`.

### `processing.parsers.surya_ocr_model._PlainTextHTMLParser`

Parser HTML minimo para bloques Surya que devuelven HTML, especialmente tablas.
Inserta separadores en tags de bloque y tags de celda, acumula texto y lo
normaliza despues.

## Chunking

### `processing.chunking.docling_chunker.ChunkMarkdownTableSerializer`

Serializer de tablas Markdown usado por Docling chunking.

Problema que resuelve:

- Al partir tablas, los chunks sin cabecera pierden contexto.
- Docling puede repetir cabeceras, pero esta clase detecta una cabecera Markdown
  mas robusta, incluyendo filas extra que parecen cabecera.

Metodo:

- `get_header_and_body_lines(table_text, **kwargs)`: separa lineas de cabecera y
  cuerpo. Si no detecta separador Markdown valido, devuelve la tabla intacta.

### `processing.chunking.docling_chunker.MarkdownChunkingSerializerProvider`

Proveedor para Docling `HybridChunker`. Mantiene la metadata de chunk de Docling
pero reemplaza el serializer de tablas por `ChunkMarkdownTableSerializer`.

Metodo:

- `get_serializer(doc)`: devuelve `ChunkingDocSerializer` con serializer de tabla
  custom.

### `processing.chunking.docling_chunker.DoclingChunker`

Convierte un `ParsedDocument` en `DocumentChunk` listo para indexar.

Constantes clave:

- `SPARSE_CHUNK_MAX_TOKENS = 512`: limite real para texto sparse.
- `CHUNK_MIN_TARGET_TOKENS = 128`: chunks menores intentan fusionarse.
- `CHUNK_OVERLAP_TOKENS = 100`: overlap al partir textos largos manualmente.
- `MARKDOWN_SINGLE_CHUNK_MAX_TOKENS = 512`: Markdown/JSON pequeno sin paginas se
  indexa como un solo chunk.

Inicializacion:

- Solo acepta `chunk_type="token"`.
- Rechaza `chunk_max_tokens <= 0`.
- Aplica `min(server_config.chunk_max_tokens, 512)` porque Elasticsearch sparse
  debe recibir chunks pequenos.
- Crea y cachea `HybridChunker` con tokenizer local (`local_files_only=True`).

Metodo publico:

- `chunk(doc, progress)`: genera chunks, fusiona chunks cortos cuando no rompe el
  limite sparse, actualiza contador y devuelve lista final.

Proceso interno:

- Si el documento es Markdown/JSON preprocesado sin paginas y cabe en 512 tokens,
  crea un solo `DocumentChunk`.
- Si no, usa `HybridChunker` sobre `document.original_out_doc.raw`.
- Para cada `DocChunk`, toma texto base y texto contextualizado; prefiere el
  contextualizado si existe.
- Extrae `doc_items`, paginas y headings desde metadata Docling.
- Si un contenido supera 512 tokens, lo parte con tokenizer; si el tokenizer no
  expone `encode/decode`, cae a particion por palabras.
- Fusiona chunks cortos hacia delante y luego cola corta hacia atras si el merge
  sigue dentro del limite.
- Renumera `chunk_index` y `chunk_id` despues de fusionar.
- `DocumentChunk.content_sparse` se iguala a `content`; Elasticsearch rellena
  dense/sparse segun pipeline.

## Worker y carpeta compartida

### `workers.inbound_worker.InboundWorker`

Consumidor background de la cola local.

Inicializacion:

- Recibe `stop_event`, `metrics_store` y opcionalmente `server_config`.
- Usa `local_queue`.
- Crea `BoundedSemaphore(worker_max_workers)` para no sacar mas jobs que slots.
- Crea `ProcessPoolExecutor` con contexto `spawn` y `max_tasks_per_child=1` para
  aislar memoria/GPU entre jobs.

Metodos:

- `run_forever()`: mientras no haya stop, adquiere slot, lee cola, envia
  `job_runner(job, metrics_store)` al pool y registra callbacks.
- `_on_job_done(job, future)`: fuerza `future.result()`, loguea exito o marca
  fallo en metricas si el proceso propaga excepcion.
- `shutdown()`: cancela futures pendientes y no espera al pool.

Detalle importante:

- `queue.task_done()` y liberacion de semaforo ocurren por callbacks del future,
  no justo despues del submit. Asi el worker no dequea mas trabajos que procesos
  reales disponibles.

### `workers.shared_ingest.SharedFolderScanner`

Scanner de carpetas compartidas para ingest sin pasar por upload HTTP.

Estructura esperada:

```text
SHARED_INGEST_DIR/
  <coleccion>/
    archivo.pdf
    output/
      .ingest-state.json
      <job_id>/
        <titulo> output.md
        chunks/*.json
```

Metodos:

- `run_forever()`: ejecuta `scan_once()` cada
  `shared_ingest_scan_interval_seconds`.
- `scan_once()`: crea carpetas de coleccion, recorre archivos candidatos,
  detecta cambios, crea `Job`, crea metricas, encola y actualiza state.
- `_ensure_collection_folders()`: crea carpetas para el indice configurado y para
  indices `open-rag-*` existentes en Elasticsearch.
- `_elastic_collection_names()`: consulta mappings para descubrir colecciones.
- `_is_collection_dir(path)`: acepta directorios visibles que no sean `output`.
- `_is_candidate_file(path)`: acepta archivos visibles y evita temporales
  (`.tmp`, `.part`, `.crdownload`, `.download`).
- `_is_stable(path)`: espera a que el mtime tenga la edad configurada para no
  leer archivos aun copiandose.
- `_file_identity(path)`: usa path resuelto, `mtime_ns` y tamano.
- `_load_state` / `_write_state`: leen/escriben `.ingest-state.json`; escritura
  atomica via `.tmp` y `replace`.
- `_build_job(...)`: genera job `docling/token`, collection canonical,
  `task_id`, MIME guess y metadata de carpeta compartida.

Funciones relacionadas:

- `canonical_collection_name(value, config)`: normaliza nombres a
  `open-rag-<slug>`.
- `shared_output_dir_for_collection(...)`: carpeta `output` por coleccion.
- `shared_output_dir_for_job(...)`: carpeta de output por job.
- `shared_output_markdown_for_job_id(...)`: busca Markdown final de un job.
- `shared_collection_names(config)`: lista colecciones existentes en disco.
- `update_shared_ingest_state(job, status, error=None)`: marca `done`/`failed`
  en state solo si el job viene de `source="shared-folder"`.

## Elasticsearch

### `dispatcher.elastic.elastic.ElasticsearchDispatch`

Frontera con Elasticsearch. Crea cliente, asegura pipeline/indice y hace bulk
indexing de `DocumentChunk`.

Inicializacion:

- Toma valores de `ServerConfig`.
- Permite overrides por `**data`, usado para mandar un job a otro indice con
  `elastic_index_name`.
- Construye cliente con hosts, API key opcional, TLS y compresion.
- Ejecuta `_ensure_pipeline()` y `_ensure_index()` al crear la instancia.

Pipeline:

- `OPEN_RAG_PIPELINE` fija `ingested_at`.
- Escapa `${` en campos usados por inference templates.
- Normaliza titulo, `clean_title`, headings y campos auxiliares.
- Rellena `content_dense` y `content_sparse` desde `content` si vienen vacios.
- Quita campos legacy (`content_semantic`, `raw_data`, etc.).
- En fallo de ingest, escribe `ingest_error`.

Mappings:

- `content` queda como `text`.
- `content_dense` es `semantic_text` dense con inference/search inference IDs.
- `content_sparse`, `clean_title` y `headings` son `semantic_text` sparse con
  `naver-splade-v3`.
- `_source` excluye dense/sparse para no duplicar embeddings/texto generado.
- `document_metadata` queda `enabled: false`.
- Si el indice ya existe, solo intenta recuperar mappings de campos simples
  (`collection_name`, `task_id`, `source_size_bytes`, `document_metadata`).

Metodos:

- `close()`: cierra cliente si existe `close`.
- `dispatch_chunks(chunks)`: divide por `bulk_batch_size`, manda bulk con
  pipeline, espera refresh y reintenta solo items con status retryable.
- `_bulk_operations(chunks)`: construye pares action/document para bulk.
- `_failed_bulk_items(response_body)`: extrae items con error.
- `_retryable_failed_item_ids(failed_items)`: devuelve `_id` de errores 429/5xx.
- `_bulk_item_retry_delay_seconds(retry_count)`: backoff exponencial hasta 30s.
- `dispatch_markdown(markdown)`: no implementado; el sistema indexa chunks, no
  Markdown completo.

## Tests y clases auxiliares

Las clases de `tests/` no son runtime, pero sirven como mapa de comportamiento:

- `ServerConfigTest`: defaults, overrides env, constantes, GPU env, mappings,
  pipeline y validacion de `DOCLING_TABLE_MODE`.
- `JsonToMarkdownPreprocessorTest`: conversion de JSON a Markdown.
- `DoclingParserTest`: deteccion de formato, titulo, JSON como Markdown,
  opciones Docling y engines OCR.
- `DoclingChunkerTest`: limite sparse 512, tokenizer, payload RAG, single chunk
  Markdown, coalescing, split por limite y metadata.
- `ChunkMarkdownTableSerializerTest`: cabeceras Markdown repetibles en tablas.
- `MinerUOcrModelTest`: bbox normalizada, filtros de bloques, opciones MinerU y
  reparaciones de checkpoint.
- `SuryaOcrModelTest`: bbox/polygon, HTML a texto, opciones Surya y env vars.
- `JobMetricsStoreTest`: lifecycle exitoso, fallo y filtros.
- `InboundWorkerTest`: concurrencia de un worker y callbacks.
- `JobRunnerTest`: errores serializables, nombres de salida, escritura de
  Markdown/chunks, output antes de fallo dispatch y override de indice.
- `SharedIngestTest`: nombres de coleccion, carpetas, estabilidad, requeue por
  cambio, skips y state.
- `ElasticsearchDispatchTest`: pipeline, mappings, bulk ops, retry y fallos.
- `FrontendAdapterTest` y `MetricsApiTest`: adaptador API/frontend y endpoints.
- `TitleNormalizationTest`: limpieza de titulos.
- `RagWorkflowTest`: consistencia del workflow RAG versionado.

Fakes utiles en tests:

- `FakeTokenizer`, `FakeDoclingChunker`, `FakeMarkdownDocument`: aíslan chunking.
- `FakeFuture`, `FakeProcessPoolExecutor`: aíslan worker concurrente.
- `FakeElasticsearch`, `FakeIndices`, `FakeClient`, `FakeBulkClient`: aíslan
  integracion Elasticsearch sin cluster real.
- `UnpickleableError`: valida que `job_runner` convierta excepciones no
  serializables a `RuntimeError`.
