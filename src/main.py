from contextlib import asynccontextmanager
import logging
import mimetypes
from os import getenv
from multiprocessing import Manager
from multiprocessing.connection import Listener
from pathlib import Path
import shutil
import sys
from threading import Thread, Event
from typing import Any
from uuid import uuid4


APP_MODULE_DIR = Path(__file__).resolve().parent / "ingest-server-orquestator"
if str(APP_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(APP_MODULE_DIR))

from config.gpu import configure_gpu_environment

# Must run before importing worker/parser modules that can load CUDA libraries.
configure_gpu_environment()

from fastapi import FastAPI
from fastapi import Body
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi import UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from api.frontend_adapter import router as frontend_adapter_router
from config.config import load_server_config
from config.paths import OUTPUT_DIR, UPLOAD_DIR
from dispatcher.elastic.elastic import ElasticsearchDispatch
from metrics.store import JobMetricsStore
from queues.domain.job import Job
from queues.queue_local import local_queue
from workers.inbound_worker import InboundWorker


logging.basicConfig(
    level=getenv("INGEST_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    force=True,
)
LOGGER = logging.getLogger("ingest-server-orquestator.api")

_PRIVATE_JOB_FIELDS = {"output_path"}
_CASE_ELASTIC_INDEX_NAME = "case-rag"


def _build_metrics_store() -> tuple[object | None, JobMetricsStore]:
    if not _can_start_manager_listener():
        return None, JobMetricsStore()
    try:
        metrics_manager = Manager()
    except (EOFError, OSError):
        return None, JobMetricsStore()
    return metrics_manager, JobMetricsStore(metrics_manager.dict())


def _can_start_manager_listener() -> bool:
    try:
        listener = Listener(address=None)
    except OSError:
        return False
    listener.close()
    return True


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


def _case_filename(payload: dict[str, Any]) -> str:
    filename = _safe_filename(
        str(payload.get("title") or payload.get("case_id") or "case")
    )
    if Path(filename).suffix.lower() not in {".md", ".markdown"}:
        filename = f"{filename}.md"
    return filename


def _save_markdown_case(content: str, filename: str) -> tuple[Path, int]:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target_path = UPLOAD_DIR / f"{uuid4().hex}-{filename}"
    target_path.write_text(content, encoding="utf-8")
    return target_path, target_path.stat().st_size


def _validated_output_path(job: dict[str, Any]) -> Path:
    output_path = job.get("output_path")
    if not output_path:
        raise HTTPException(status_code=404, detail="Job output not found")

    path = Path(str(output_path))
    if not path.is_absolute():
        path = OUTPUT_DIR / path

    output_root = OUTPUT_DIR.resolve()
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(output_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Job output not found") from exc

    if not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="Job output not found")

    return resolved_path


def _output_path_for_job_id(job_id: str) -> Path | None:
    output_dir = (OUTPUT_DIR / job_id).resolve()
    output_root = OUTPUT_DIR.resolve()
    try:
        output_dir.relative_to(output_root)
    except ValueError:
        return None
    if not output_dir.is_dir():
        return None
    markdown_files = sorted(output_dir.glob("*.md"))
    return markdown_files[0] if markdown_files else None


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in job.items()
        if key not in _PRIVATE_JOB_FIELDS
    }


def _ensure_elasticsearch_index(server_config) -> None:
    dispatcher = ElasticsearchDispatch(server_config=server_config)
    dispatcher.close()


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    fastapi_app.state.server_config = load_server_config()
    LOGGER.info(
        "Starting ingest API app=%s env=%s upload_dir=%s",
        fastapi_app.state.server_config.app_name,
        fastapi_app.state.server_config.environment,
        UPLOAD_DIR,
    )
    LOGGER.info(
        "Ensuring Elasticsearch pipeline/index index=%s pipeline=%s",
        fastapi_app.state.server_config.elastic_index_name,
        fastapi_app.state.server_config.elastic_pipeline_name,
    )
    _ensure_elasticsearch_index(fastapi_app.state.server_config)
    LOGGER.info("Elasticsearch pipeline/index ready")

    fastapi_app.state.metrics_manager, fastapi_app.state.metrics_store = (
        _build_metrics_store()
    )
    fastapi_app.state.frontend_collections = {}
    fastapi_app.state.frontend_deleted_collections = set()

    stop_event = Event()
    inbound_worker = InboundWorker(
        stop_event,
        fastapi_app.state.metrics_store,
        server_config=fastapi_app.state.server_config,
    )
    inbound_thread = Thread(
        target=inbound_worker.run_forever,
        name="inbound-worker",
        daemon=True,
    )
    inbound_thread.start()
    LOGGER.info("Inbound worker thread started")

    fastapi_app.state.inbound_worker_stop_event = stop_event
    fastapi_app.state.inbound_worker_thread = inbound_thread
    fastapi_app.state.inbound_worker = inbound_worker

    yield

    stop_event.set()
    inbound_thread.join(timeout=5)
    inbound_worker.shutdown()
    if fastapi_app.state.metrics_manager is not None:
        fastapi_app.state.metrics_manager.shutdown()
    LOGGER.info("Ingest API shutdown complete")

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(frontend_adapter_router)


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.post("/api/v1/ingest/file")
async def ingest_file(
    request: Request,
    file: UploadFile = File(...),
    source: str = Form("api"),
):
    server_config = request.app.state.server_config
    filename = _safe_filename(file.filename)
    content_type = _content_type(file, filename)
    stored_path, size_bytes = _save_upload(file, filename)
    LOGGER.info(
        "Received upload filename=%s content_type=%s size_bytes=%s stored_path=%s",
        filename,
        content_type,
        size_bytes,
        stored_path,
    )

    job = Job.create(
        parser_type="docling",
        input_data={
            "source": source,
            "file_name": filename,
            "file_path": str(stored_path),
            "mime_type": content_type,
            "size_bytes": size_bytes,
        },
        chunker_type="token",
        settings={"queue": server_config.inbound_queue_name},
    )
    # queue_message = job.to_queue_message()

    request.app.state.metrics_store.create_for_job(job)
    local_queue.put(job)
    LOGGER.info(
        "Queued ingest job job_id=%s queue=%s file_path=%s",
        job.job_id,
        server_config.inbound_queue_name,
        stored_path,
    )

    return {
        "job": job.to_queue_message(),
        "queue": server_config.inbound_queue_name,
        "job_status_url": f"/api/v1/ingest/jobs/{job.job_id}",
        "next_step": "processing worker picks the job and sends result to dispatcher",
    }


@app.post("/api/v1/ingest/case")
async def ingest_case(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(
            status_code=400,
            detail="content must be a non-empty Markdown string",
        )

    server_config = request.app.state.server_config
    filename = _case_filename(payload)
    stored_path, size_bytes = _save_markdown_case(content, filename)
    document_metadata = {
        key: value for key, value in payload.items() if key != "content"
    }
    source = str(payload.get("source") or "elastic-workflow")
    LOGGER.info(
        "Received case JSON filename=%s size_bytes=%s stored_path=%s",
        filename,
        size_bytes,
        stored_path,
    )

    job = Job.create(
        parser_type="docling",
        input_data={
            "source": source,
            "file_name": filename,
            "file_path": str(stored_path),
            "mime_type": "text/markdown",
            "size_bytes": size_bytes,
            "collection_name": _CASE_ELASTIC_INDEX_NAME,
            "document_metadata": document_metadata,
        },
        chunker_type="token",
        settings={
            "queue": server_config.inbound_queue_name,
            "elastic_index_name": _CASE_ELASTIC_INDEX_NAME,
        },
    )

    request.app.state.metrics_store.create_for_job(job)
    request.app.state.metrics_store.update(
        job.job_id,
        collection_name=_CASE_ELASTIC_INDEX_NAME,
        document_metadata=document_metadata,
        deleted=False,
    )
    local_queue.put(job)
    LOGGER.info(
        "Queued case ingest job job_id=%s queue=%s file_path=%s index=%s",
        job.job_id,
        server_config.inbound_queue_name,
        stored_path,
        _CASE_ELASTIC_INDEX_NAME,
    )

    return {
        "job": job.to_queue_message(),
        "queue": server_config.inbound_queue_name,
        "job_status_url": f"/api/v1/ingest/jobs/{job.job_id}",
        "next_step": "processing worker picks the job and sends result to dispatcher",
    }


@app.get("/api/v1/ingest/jobs")
async def ingest_jobs(
    request: Request,
    status: str | None = None,
    stage: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
):
    jobs = request.app.state.metrics_store.list(
        status=status,
        stage=stage,
        limit=limit,
    )
    public_jobs = [_public_job(job) for job in jobs]
    return {"jobs": public_jobs, "count": len(public_jobs)}


@app.get("/api/v1/ingest/jobs/{job_id}")
async def ingest_job(request: Request, job_id: str):
    job = request.app.state.metrics_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job metrics not found")
    return {"job": _public_job(job)}


@app.get("/api/v1/ingest/jobs/{job_id}/output")
async def ingest_job_output(request: Request, job_id: str):
    job = request.app.state.metrics_store.get(job_id)
    if job is None:
        path = _output_path_for_job_id(job_id)
        if path is None:
            raise HTTPException(status_code=404, detail="Job output not found")
        filename = path.name
    else:
        path = _validated_output_path(job)
        filename = str(job.get("output_file_name") or path.name)
    return FileResponse(
        path=path,
        filename=filename,
        media_type="text/markdown",
    )
