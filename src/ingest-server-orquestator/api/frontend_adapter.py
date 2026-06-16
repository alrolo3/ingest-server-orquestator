from __future__ import annotations

import json
import logging
import mimetypes
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Body
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi import UploadFile
from fastapi.responses import StreamingResponse

from config.config import ServerConfig
from config.config import load_server_config
from config.paths import OUTPUT_DIR
from config.paths import UPLOAD_DIR
from metrics.store import JobMetricsStore
from queues.domain.job import Job
from queues.queue_local import local_queue


router = APIRouter()
LOGGER = logging.getLogger("ingest-server-orquestator.frontend-adapter")

_DEFAULT_METADATA_SCHEMA = [
    {
        "name": "source",
        "type": "string",
        "description": "Upload source.",
    },
    {
        "name": "status",
        "type": "string",
        "description": "Ingest processing status.",
    },
    {
        "name": "stage",
        "type": "string",
        "description": "Current ingest processing stage.",
    },
    {
        "name": "job_id",
        "type": "string",
        "description": "Ingest job identifier.",
    },
]

_ELASTIC_DOCUMENT_SOURCE_FIELDS = [
    "document_id",
    "source_file_name",
    "collection_name",
    "task_id",
    "source_size_bytes",
    "title",
    "clean_title",
    "headings",
    "total_pages",
    "content",
    "ingested_at",
    "document_metadata",
]


def _server_config(request: Request) -> ServerConfig:
    return getattr(request.app.state, "server_config", load_server_config())


def _metrics_store(request: Request) -> JobMetricsStore:
    store = getattr(request.app.state, "metrics_store", None)
    if store is None:
        store = JobMetricsStore()
        request.app.state.metrics_store = store
    return store


def _state_dict(request: Request, name: str) -> dict[str, Any]:
    value = getattr(request.app.state, name, None)
    if value is None:
        value = {}
        setattr(request.app.state, name, value)
    return value


def _state_set(request: Request, name: str) -> set[str]:
    value = getattr(request.app.state, name, None)
    if value is None:
        value = set()
        setattr(request.app.state, name, value)
    return value


def _elasticsearch_client(request: Request, config: ServerConfig) -> Any | None:
    state = request.app.state
    if hasattr(state, "elasticsearch_client"):
        return getattr(state, "elasticsearch_client")
    if not config.elastic_hosts:
        return None
    try:
        from elasticsearch import Elasticsearch
    except ImportError:
        LOGGER.warning("Elasticsearch client is unavailable; skipping index recovery.")
        return None

    client = Elasticsearch(
        hosts=config.elastic_hosts,
        api_key=config.elastic_api_key,
        verify_certs=config.elastic_verify_certs,
        ssl_show_warn=config.elastic_ssl_show_warn,
        http_compress=config.elastic_http_compress,
    )
    setattr(state, "elasticsearch_client", client)
    return client


def _safe_filename(filename: str | None) -> str:
    name = Path((filename or "upload").replace("\\", "/")).name
    return name or "upload"


def _content_type(file: UploadFile, filename: str) -> str:
    return (
        file.content_type
        or mimetypes.guess_type(filename)[0]
        or "application/octet-stream"
    )


def _save_upload(file: UploadFile, filename: str) -> tuple[Path, int]:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target_path = UPLOAD_DIR / f"{uuid4().hex}-{filename}"
    file.file.seek(0)
    with target_path.open("wb") as output_file:
        shutil.copyfileobj(file.file, output_file)
    return target_path, target_path.stat().st_size


def _parse_upload_data(data: str) -> dict[str, Any]:
    if not data.strip():
        return {}
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid upload metadata JSON") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="Upload metadata must be an object")
    return parsed


def _metadata_for_file(payload: dict[str, Any], filename: str) -> dict[str, Any]:
    custom_metadata = payload.get("custom_metadata")
    if isinstance(custom_metadata, list):
        for item in custom_metadata:
            if not isinstance(item, dict):
                continue
            if item.get("filename") == filename and isinstance(item.get("metadata"), dict):
                return dict(item["metadata"])
    if isinstance(custom_metadata, dict):
        value = custom_metadata.get(filename)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _job_collection(job: dict[str, Any], config: ServerConfig) -> str:
    value = job.get("collection_name") or config.elastic_index_name
    return str(value)


def _visible_jobs(
    store: JobMetricsStore,
    config: ServerConfig,
    *,
    collection_name: str | None = None,
) -> list[dict[str, Any]]:
    jobs = [
        job
        for job in store.list(limit=None)
        if not bool(job.get("deleted"))
    ]
    if collection_name:
        jobs = [
            job
            for job in jobs
            if _job_collection(job, config) == collection_name
        ]
    return sorted(jobs, key=lambda job: str(job.get("created_at") or ""))


def _collection_filter(collection_name: str, config: ServerConfig) -> dict[str, Any]:
    if collection_name != config.elastic_index_name:
        return {"term": {"collection_name": collection_name}}
    return {
        "bool": {
            "should": [
                {"term": {"collection_name": collection_name}},
                {"bool": {"must_not": [{"exists": {"field": "collection_name"}}]}},
            ],
            "minimum_should_match": 1,
        }
    }


def _elastic_document_query(
    config: ServerConfig,
    *,
    collection_name: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    filters: list[dict[str, Any]] = []
    if collection_name:
        filters.append(_collection_filter(collection_name, config))
    if task_id:
        filters.append({"term": {"task_id": task_id}})

    query: dict[str, Any] = {"match_all": {}}
    if filters:
        query = {"bool": {"filter": filters}}

    return {
        "size": 0,
        "query": query,
        "aggs": {
            "documents": {
                "terms": {
                    "field": "document_id",
                    "size": 1000,
                    "order": {"last_ingested": "desc"},
                },
                "aggs": {
                    "first_chunk": {
                        "top_hits": {
                            "size": 1,
                            "sort": [
                                {
                                    "chunk_index": {
                                        "order": "asc",
                                        "unmapped_type": "integer",
                                    }
                                }
                            ],
                            "_source": {"includes": _ELASTIC_DOCUMENT_SOURCE_FIELDS},
                        }
                    },
                    "last_ingested": {"max": {"field": "ingested_at"}},
                    "first_ingested": {"min": {"field": "ingested_at"}},
                    "total_pages": {"max": {"field": "total_pages"}},
                },
            }
        },
    }


def _response_body(response: Any) -> dict[str, Any]:
    body = getattr(response, "body", response)
    return body if isinstance(body, dict) else {}


def _date_agg_value(bucket: dict[str, Any], name: str) -> str | None:
    value = bucket.get(name)
    if not isinstance(value, dict):
        return None
    if value.get("value_as_string"):
        return str(value["value_as_string"])
    if value.get("value") is not None:
        return str(value["value"])
    return None


def _first_hit_source(bucket: dict[str, Any]) -> dict[str, Any]:
    hits = (
        bucket.get("first_chunk", {})
        .get("hits", {})
        .get("hits", [])
    )
    if not hits:
        return {}
    source = hits[0].get("_source", {})
    return source if isinstance(source, dict) else {}


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _elastic_document_jobs(
    request: Request,
    config: ServerConfig,
    *,
    collection_name: str | None = None,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    client = _elasticsearch_client(request, config)
    if client is None:
        return []
    try:
        response = client.search(
            index=config.elastic_index_name,
            body=_elastic_document_query(
                config,
                collection_name=collection_name,
                task_id=task_id,
            ),
        )
    except Exception as exc:
        LOGGER.warning("Failed to recover document state from Elasticsearch: %s", exc)
        return []

    buckets = (
        _response_body(response)
        .get("aggregations", {})
        .get("documents", {})
        .get("buckets", [])
    )
    jobs = []
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        source = _first_hit_source(bucket)
        document_id = str(source.get("document_id") or bucket.get("key") or "")
        if not document_id:
            continue
        file_name = str(
            source.get("source_file_name")
            or source.get("clean_title")
            or source.get("title")
            or document_id
        )
        document_metadata = source.get("document_metadata")
        total_pages = source.get("total_pages")
        if isinstance(bucket.get("total_pages"), dict):
            total_pages = bucket["total_pages"].get("value", total_pages)
        created_at = _date_agg_value(bucket, "first_ingested") or source.get("ingested_at")
        finished_at = _date_agg_value(bucket, "last_ingested") or source.get("ingested_at")
        jobs.append(
            {
                "job_id": document_id,
                "file_name": file_name,
                "source": "elasticsearch",
                "status": "done",
                "stage": "done",
                "collection_name": str(
                    source.get("collection_name") or config.elastic_index_name
                ),
                "task_id": source.get("task_id"),
                "size_bytes": _int_or_none(source.get("source_size_bytes")),
                "created_at": created_at,
                "updated_at": finished_at,
                "finished_at": finished_at,
                "chunks_created": int(bucket.get("doc_count") or 0),
                "chunks_dispatched": int(bucket.get("doc_count") or 0),
                "total_pages": _int_or_none(total_pages),
                "output_url": f"/api/v1/ingest/jobs/{document_id}/output",
                "document_metadata": (
                    document_metadata if isinstance(document_metadata, dict) else {}
                ),
                "document_excerpt": source.get("content"),
                "title": source.get("title"),
                "clean_title": source.get("clean_title"),
                "headings": source.get("headings") or [],
                "recovered_from": "elasticsearch",
            }
        )
    return sorted(jobs, key=lambda job: str(job.get("created_at") or ""))


def _visible_jobs_for_request(
    request: Request,
    *,
    collection_name: str | None = None,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    config = _server_config(request)
    store = _metrics_store(request)
    memory_jobs = _visible_jobs(store, config, collection_name=collection_name)
    if task_id:
        memory_jobs = [job for job in memory_jobs if job.get("task_id") == task_id]
    elastic_jobs = _elastic_document_jobs(
        request,
        config,
        collection_name=collection_name,
        task_id=task_id,
    )
    merged = {str(job.get("job_id") or ""): job for job in elastic_jobs}
    for job in memory_jobs:
        job_id = str(job.get("job_id") or "")
        if job_id:
            merged[job_id] = job
    return sorted(merged.values(), key=lambda job: str(job.get("created_at") or ""))


def _collection_status(jobs: list[dict[str, Any]]) -> str:
    if any(job.get("status") == "failed" for job in jobs):
        return "failed"
    if any(job.get("status") in {"queued", "running"} for job in jobs):
        return "processing"
    if jobs:
        return "ready"
    return "empty"


def _last_job_timestamp(jobs: list[dict[str, Any]]) -> str | None:
    values = [
        str(job.get("finished_at") or job.get("updated_at") or "")
        for job in jobs
        if job.get("finished_at") or job.get("updated_at")
    ]
    return max(values) if values else None


def _collection_record(
    *,
    name: str,
    config: ServerConfig,
    jobs: list[dict[str, Any]],
    stored_collection: dict[str, Any] | None,
) -> dict[str, Any]:
    collection_info = dict(stored_collection or {})
    metadata_schema = collection_info.pop("metadata_schema", None) or list(
        _DEFAULT_METADATA_SCHEMA
    )
    file_names = {str(job.get("file_name") or "") for job in jobs if job.get("file_name")}
    num_entities = sum(
        int(job.get("chunks_dispatched") or job.get("chunks_created") or 0)
        for job in jobs
    )
    collection_info.setdefault("description", "Ingest server Elasticsearch target index.")
    collection_info.setdefault("tags", ["ingest-server", "elasticsearch"])
    collection_info.setdefault("status", "Active")
    collection_info.setdefault("number_of_files", len(file_names))
    collection_info.setdefault("last_indexed", _last_job_timestamp(jobs))
    collection_info.setdefault("ingestion_status", _collection_status(jobs))
    collection_info.setdefault(
        "doc_type_counts",
        {"text": sum(int(job.get("chunks_created") or 0) for job in jobs)},
    )
    return {
        "collection_name": name,
        "num_entities": num_entities,
        "metadata_schema": metadata_schema,
        "collection_info": collection_info,
    }


def _collections(request: Request) -> list[dict[str, Any]]:
    config = _server_config(request)
    stored = _state_dict(request, "frontend_collections")
    deleted = _state_set(request, "frontend_deleted_collections")
    jobs = _visible_jobs_for_request(request)
    names = {config.elastic_index_name}
    names.update(stored)
    names.update(_job_collection(job, config) for job in jobs)
    records = []
    for name in sorted(names):
        if name in deleted:
            continue
        collection_jobs = [
            job
            for job in jobs
            if _job_collection(job, config) == name
        ]
        records.append(
            _collection_record(
                name=name,
                config=config,
                jobs=collection_jobs,
                stored_collection=stored.get(name),
            )
        )
    return records


def _document_job(
    *,
    request: Request,
    collection_name: str,
    document_name: str,
) -> dict[str, Any] | None:
    for job in _visible_jobs_for_request(request, collection_name=collection_name):
        if job.get("file_name") == document_name or job.get("job_id") == document_name:
            return job
    return None


def _document_item(job: dict[str, Any]) -> dict[str, Any]:
    metadata = {
        "filename": str(job.get("file_name") or ""),
        "job_id": str(job.get("job_id") or ""),
        "source": str(job.get("source") or ""),
        "status": str(job.get("status") or ""),
        "stage": str(job.get("stage") or ""),
    }
    if job.get("recovered_from"):
        metadata["recovered_from"] = str(job["recovered_from"])
    if job.get("output_url"):
        metadata["output_url"] = str(job["output_url"])
    document_metadata = job.get("document_metadata")
    if isinstance(document_metadata, dict):
        metadata.update(document_metadata)
    document_info = {
        "description": job.get("document_description"),
        "tags": job.get("document_tags") or [],
        "file_size": job.get("size_bytes"),
        "date_created": job.get("created_at"),
        "total_elements": job.get("chunks_created") or 0,
        "total_pages": job.get("total_pages"),
        "doc_type_counts": {"text": job.get("chunks_created") or 0},
    }
    return {
        "document_name": str(job.get("file_name") or job.get("job_id") or "document"),
        "metadata": metadata,
        "document_info": document_info,
    }


def _output_path_for_document_id(document_id: str) -> Path | None:
    output_dir = (OUTPUT_DIR / document_id).resolve()
    output_root = OUTPUT_DIR.resolve()
    try:
        output_dir.relative_to(output_root)
    except ValueError:
        return None
    if not output_dir.is_dir():
        return None
    markdown_files = sorted(output_dir.glob("*.md"))
    return markdown_files[0] if markdown_files else None


def _task_state(jobs: list[dict[str, Any]]) -> str:
    if any(job.get("status") in {"queued", "running"} for job in jobs):
        return "PENDING"
    if any(job.get("status") == "failed" for job in jobs):
        return "FAILED"
    if jobs:
        return "FINISHED"
    return "UNKNOWN"


def _task_response(task_id: str, jobs: list[dict[str, Any]], config: ServerConfig) -> dict[str, Any]:
    collection_name = _job_collection(jobs[0], config) if jobs else config.elastic_index_name
    state = _task_state(jobs)
    completed_jobs = [
        job
        for job in jobs
        if job.get("status") in {"done", "failed"}
    ]
    done_jobs = [job for job in jobs if job.get("status") == "done"]
    failed_jobs = [job for job in jobs if job.get("status") == "failed"]
    return {
        "id": task_id,
        "collection_name": collection_name,
        "created_at": min(str(job.get("created_at") or "") for job in jobs) if jobs else "",
        "state": state,
        "documents": [str(job.get("file_name") or "") for job in jobs],
        "result": {
            "message": f"{len(completed_jobs)}/{len(jobs)} documents completed.",
            "total_documents": len(jobs),
            "documents": [
                {
                    "document_id": str(job.get("job_id") or ""),
                    "document_name": str(job.get("file_name") or ""),
                    "size_bytes": job.get("size_bytes"),
                }
                for job in done_jobs
            ],
            "failed_documents": [
                {
                    "document_name": str(job.get("file_name") or ""),
                    "error_message": str(job.get("error") or "Ingest failed."),
                }
                for job in failed_jobs
            ],
            "documents_completed": len(completed_jobs),
            "batches_completed": len(completed_jobs),
        },
    }


@router.get("/api/health")
async def frontend_health(
    request: Request,
    check_dependencies: bool = Query(False),
) -> dict[str, Any]:
    config = _server_config(request)
    elastic_url = ",".join(config.elastic_hosts)
    return {
        "message": "Ingest server frontend adapter is healthy.",
        "databases": [
            {
                "service": "Elasticsearch",
                "url": elastic_url,
                "status": "healthy" if elastic_url else "skipped",
                "latency_ms": 0,
                "error": None,
                "collections": [collection["collection_name"] for collection in _collections(request)],
            }
        ],
        "object_storage": [
            {
                "service": "Local filesystem",
                "url": str(UPLOAD_DIR),
                "status": "healthy",
                "latency_ms": 0,
                "error": None,
                "buckets": 2,
                "message": f"uploads={UPLOAD_DIR} outputs={OUTPUT_DIR}",
            }
        ],
        "nim": [
            {
                "service": "Embedding Model",
                "url": "Elasticsearch inference endpoint",
                "status": "healthy",
                "latency_ms": 0,
                "error": None,
                "model": config.elastic_inference_id,
                "message": "Embeddings are generated by Elasticsearch semantic_text inference.",
                "http_status": 200,
            }
        ],
        "processing": [
            {
                "service": "Docling ingest worker",
                "url": "local-queue",
                "status": "healthy",
                "latency_ms": 0,
                "error": None,
                "http_status": 200,
            }
        ],
        "task_management": [
            {
                "service": "LocalQueue",
                "url": config.inbound_queue_name,
                "status": "healthy",
                "latency_ms": 0,
                "error": None,
                "message": "Frontend tasks are backed by ingest job metrics.",
            }
        ],
        "adapter": {
            "check_dependencies": check_dependencies,
            "rag_generation": "not_configured",
        },
    }


@router.get("/api/configuration")
async def frontend_configuration(request: Request) -> dict[str, Any]:
    config = _server_config(request)
    return {
        "rag_configuration": {
            "temperature": 0.2,
            "top_p": 0.95,
            "max_tokens": 1024,
            "vdb_top_k": 10,
            "reranker_top_k": 5,
            "confidence_threshold": 0.0,
        },
        "feature_toggles": {
            "enable_reranker": False,
            "enable_citations": True,
            "enable_guardrails": False,
            "enable_query_rewriting": False,
            "enable_vlm_inference": False,
            "enable_filter_generator": False,
        },
        "models": {
            "llm_model": "",
            "embedding_model": config.elastic_inference_id,
            "reranker_model": "",
            "vlm_model": config.docling_picture_description_model,
        },
        "endpoints": {
            "llm_endpoint": "",
            "embedding_endpoint": "Elasticsearch semantic_text inference",
            "reranker_endpoint": "",
            "vlm_endpoint": config.docling_picture_description_url,
            "vdb_endpoint": ",".join(config.elastic_hosts),
        },
    }


@router.get("/api/collections")
async def frontend_collections(request: Request) -> dict[str, Any]:
    collections = _collections(request)
    return {"collections": collections, "count": len(collections)}


@router.post("/api/collection")
async def frontend_create_collection(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    collection_name = str(payload.get("collection_name") or "").strip()
    if not collection_name:
        raise HTTPException(status_code=400, detail="collection_name is required")
    stored = _state_dict(request, "frontend_collections")
    deleted = _state_set(request, "frontend_deleted_collections")
    deleted.discard(collection_name)
    stored[collection_name] = {
        "metadata_schema": payload.get("metadata_schema") or list(_DEFAULT_METADATA_SCHEMA),
        "description": payload.get("description"),
        "tags": payload.get("tags") or [],
        "owner": payload.get("owner"),
        "created_by": payload.get("created_by"),
        "business_domain": payload.get("business_domain"),
        "status": payload.get("status") or "Active",
    }
    collection = next(
        item
        for item in _collections(request)
        if item["collection_name"] == collection_name
    )
    return {
        "message": "Collection registered for ingest frontend.",
        "collection": collection,
    }


@router.delete("/api/collections")
async def frontend_delete_collections(
    request: Request,
    collection_names: list[str] = Body(default=[]),
) -> dict[str, Any]:
    stored = _state_dict(request, "frontend_collections")
    deleted = _state_set(request, "frontend_deleted_collections")
    store = _metrics_store(request)
    config = _server_config(request)
    for collection_name in collection_names:
        stored.pop(collection_name, None)
        deleted.add(collection_name)
        for job in _visible_jobs(store, config, collection_name=collection_name):
            store.update(str(job["job_id"]), deleted=True)
    return {
        "message": "Collections removed from frontend catalog.",
        "collections": collection_names,
    }


@router.get("/api/documents")
async def frontend_documents(
    request: Request,
    collection_name: str = Query(...),
) -> dict[str, Any]:
    documents = [
        _document_item(job)
        for job in _visible_jobs_for_request(request, collection_name=collection_name)
    ]
    return {
        "message": "Documents fetched from ingest state.",
        "total_documents": len(documents),
        "documents": documents,
    }


@router.post("/api/documents")
async def frontend_upload_documents(
    request: Request,
    documents: list[UploadFile] = File(...),
    data: str = Form("{}"),
    blocking: bool = Query(False),
) -> dict[str, Any]:
    if not documents:
        raise HTTPException(status_code=400, detail="At least one document is required")

    config = _server_config(request)
    store = _metrics_store(request)
    payload = _parse_upload_data(data)
    collection_name = str(payload.get("collection_name") or config.elastic_index_name)
    task_id = uuid4().hex

    stored = _state_dict(request, "frontend_collections")
    deleted = _state_set(request, "frontend_deleted_collections")
    deleted.discard(collection_name)
    stored.setdefault(
        collection_name,
        {
            "metadata_schema": list(_DEFAULT_METADATA_SCHEMA),
            "description": "Collection created from NVIDIA RAG frontend upload.",
            "tags": ["ingest-server"],
            "status": "Active",
        },
    )

    queued_documents = []
    for document in documents:
        filename = _safe_filename(document.filename)
        content_type = _content_type(document, filename)
        stored_path, size_bytes = _save_upload(document, filename)
        document_metadata = _metadata_for_file(payload, filename)
        job = Job.create(
            parser_type="docling",
            input_data={
                "source": "nvidia-rag-frontend",
                "file_name": filename,
                "file_path": str(stored_path),
                "mime_type": content_type,
                "size_bytes": size_bytes,
                "collection_name": collection_name,
                "task_id": task_id,
                "document_metadata": document_metadata,
            },
            chunker_type="token",
            settings={
                "queue": config.inbound_queue_name,
                "task_id": task_id,
                "collection_name": collection_name,
                "blocking": blocking,
            },
        )
        store.create_for_job(job)
        store.update(
            job.job_id,
            task_id=task_id,
            collection_name=collection_name,
            document_metadata=document_metadata,
            deleted=False,
        )
        local_queue.put(job)
        queued_documents.append(
            {
                "document_id": job.job_id,
                "document_name": filename,
                "size_bytes": size_bytes,
            }
        )

    return {
        "message": f"Queued {len(queued_documents)} document(s) for ingest.",
        "task_id": task_id,
        "collection_name": collection_name,
        "total_documents": len(queued_documents),
        "documents": queued_documents,
        "failed_documents": [],
    }


@router.delete("/api/documents")
async def frontend_delete_documents(
    request: Request,
    collection_name: str = Query(...),
    document_names: list[str] = Body(default=[]),
) -> dict[str, Any]:
    config = _server_config(request)
    store = _metrics_store(request)
    deleted_count = 0
    for job in _visible_jobs(store, config, collection_name=collection_name):
        if document_names and job.get("file_name") not in document_names:
            continue
        store.update(str(job["job_id"]), deleted=True)
        deleted_count += 1
    return {
        "message": "Documents removed from frontend catalog.",
        "deleted": deleted_count,
        "documents": document_names,
    }


@router.patch("/api/collections/{collection_name}/documents/{document_name}/metadata")
async def frontend_update_document_metadata(
    request: Request,
    collection_name: str,
    document_name: str,
    payload: dict[str, Any] = Body(default={}),
) -> dict[str, Any]:
    store = _metrics_store(request)
    job = _document_job(
        request=request,
        collection_name=collection_name,
        document_name=document_name,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Document not found")
    store.update(
        str(job["job_id"]),
        document_description=payload.get("description"),
        document_tags=payload.get("tags") or [],
    )
    return {"message": "Document metadata updated."}


@router.get("/api/status")
async def frontend_task_status(
    request: Request,
    task_id: str = Query(...),
) -> dict[str, Any]:
    config = _server_config(request)
    jobs = _visible_jobs_for_request(request, task_id=task_id)
    if not jobs:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_response(task_id, jobs, config)


@router.get("/api/summary")
async def frontend_document_summary(
    request: Request,
    collection_name: str = Query(...),
    file_name: str = Query(...),
) -> dict[str, Any]:
    job = _document_job(
        request=request,
        collection_name=collection_name,
        document_name=file_name,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Document not found")

    if job.get("status") == "failed":
        return {
            "summary": "",
            "file_name": file_name,
            "collection_name": collection_name,
            "status": "FAILED",
            "error": job.get("error") or "Ingest failed.",
        }
    if job.get("status") != "done":
        return {
            "summary": "",
            "file_name": file_name,
            "collection_name": collection_name,
            "status": "IN_PROGRESS",
            "message": job.get("message") or "Document is still processing.",
        }

    summary = (
        f"Processed {file_name} into {job.get('chunks_created') or 0} chunks. "
        f"Markdown output is available from {job.get('output_url') or 'the job output endpoint'}."
    )
    output_path = job.get("output_path")
    if not output_path and job.get("job_id"):
        output_path = _output_path_for_document_id(str(job["job_id"]))
    if output_path:
        path = Path(str(output_path))
        if not path.is_absolute():
            path = OUTPUT_DIR / path
        try:
            if path.resolve().is_file():
                with path.open("r", encoding="utf-8", errors="ignore") as handle:
                    excerpt = handle.read(1200).strip()
                if excerpt:
                    summary = excerpt
        except OSError:
            pass
    elif job.get("document_excerpt"):
        summary = str(job["document_excerpt"]).strip()

    return {
        "summary": summary,
        "file_name": file_name,
        "collection_name": collection_name,
        "status": "SUCCESS",
    }


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return " ".join(part for part in parts if part)
    return str(content or "")


def _latest_user_message(payload: dict[str, Any]) -> str:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            return _message_text(message.get("content"))
    return ""


def _chat_answer(request: Request, payload: dict[str, Any]) -> str:
    config = _server_config(request)
    selected = payload.get("collection_names")
    if isinstance(selected, list) and selected:
        collection_names = [str(name) for name in selected]
    else:
        collection_names = [config.elastic_index_name]
    jobs = [
        job
        for collection_name in collection_names
        for job in _visible_jobs_for_request(request, collection_name=collection_name)
    ]
    done = sum(1 for job in jobs if job.get("status") == "done")
    failed = sum(1 for job in jobs if job.get("status") == "failed")
    active = len(jobs) - done - failed
    question = _latest_user_message(payload)
    return (
        "This ingest-server-orquestator deployment is wired to the NVIDIA RAG "
        "frontend for document ingest, collection browsing, job notifications, "
        "and status tracking. A RAG generation service is not configured in this "
        "backend, so I cannot answer from indexed content here. "
        f"Selected collection(s): {', '.join(collection_names)}. "
        f"Current ingest jobs: {done} done, {active} active, {failed} failed. "
        f"Last prompt received: {question or 'empty prompt'}"
    )


def _stream_chunk(content: str, *, finish_reason: str | None = None) -> str:
    payload = {
        "choices": [
            {
                "delta": {"content": content},
                "finish_reason": finish_reason,
            }
        ]
    }
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/api/generate")
async def frontend_generate(
    request: Request,
    payload: dict[str, Any] = Body(default={}),
) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        answer = _chat_answer(request, payload)
        yield _stream_chunk(answer)
        yield _stream_chunk("", finish_reason="stop")

    return StreamingResponse(stream(), media_type="text/event-stream")
