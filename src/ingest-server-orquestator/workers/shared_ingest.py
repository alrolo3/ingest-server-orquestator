from __future__ import annotations

import json
import logging
import mimetypes
import re
from pathlib import Path
from threading import Event
from time import time
from typing import Any
from uuid import uuid4

from config.config import ServerConfig, get_server_config
from metrics.store import JobMetricsStore
from queues.domain.job import Job
from queues.queue_local import local_queue


LOGGER = logging.getLogger("ingest-server-orquestator.shared-ingest")

OPEN_RAG_PREFIX = "open-rag-"
OUTPUT_DIR_NAME = "output"
STATE_FILE_NAME = ".ingest-state.json"

_SLUG_SEPARATORS = re.compile(r"[^a-z0-9]+")
_UNSAFE_PATH_CHARS = re.compile(r"[^a-zA-Z0-9._-]+")
_TEMP_SUFFIXES = (".tmp", ".part", ".crdownload", ".download")


def _safe_folder_name(value: str) -> str:
    folder = _UNSAFE_PATH_CHARS.sub("-", value.strip()).strip(".-")
    return folder or "default"


def canonical_collection_name(value: object, config: ServerConfig) -> str:
    raw = str(value or config.elastic_index_name).strip().lower()
    if raw.startswith(OPEN_RAG_PREFIX):
        raw = raw[len(OPEN_RAG_PREFIX) :]
    slug = _SLUG_SEPARATORS.sub("-", raw).strip("-")
    if not slug:
        slug = "default"
    return f"{OPEN_RAG_PREFIX}{slug}"


def shared_collection_folder_name(collection_name: object) -> str:
    raw = str(collection_name or "").strip()
    if raw.lower().startswith(OPEN_RAG_PREFIX):
        raw = raw[len(OPEN_RAG_PREFIX) :]
    return _safe_folder_name(raw)


def shared_output_dir_for_collection(
    collection_name: object,
    config: ServerConfig,
) -> Path:
    return (
        config.shared_ingest_dir
        / shared_collection_folder_name(collection_name)
        / OUTPUT_DIR_NAME
    )


def shared_output_dir_for_job(job: Job, config: ServerConfig) -> Path:
    collection_name = (
        job.input_data.get("collection_name")
        or job.settings.get("elastic_index_name")
        or config.elastic_index_name
    )
    return (
        shared_output_dir_for_collection(collection_name, config)
        / _safe_folder_name(job.job_id)
    )


def shared_output_markdown_for_job_id(
    job_id: str,
    config: ServerConfig,
) -> Path | None:
    job_folder = _safe_folder_name(job_id)
    shared_root = config.shared_ingest_dir.resolve()
    for path in sorted(shared_root.glob(f"*/{OUTPUT_DIR_NAME}/{job_folder}/*.md")):
        try:
            path.resolve().relative_to(shared_root)
        except ValueError:
            continue
        if path.is_file():
            return path
    return None


def shared_collection_names(config: ServerConfig) -> set[str]:
    root = config.shared_ingest_dir
    if not root.is_dir():
        return set()
    names = set()
    for path in root.iterdir():
        if (
            not path.is_dir()
            or path.name.startswith(".")
            or path.name == OUTPUT_DIR_NAME
        ):
            continue
        names.add(canonical_collection_name(path.name, config))
    return names


class SharedFolderScanner:
    """Poll shared collection folders and enqueue stable new or changed files."""

    def __init__(
        self,
        stop_event: Event,
        metrics_store: JobMetricsStore,
        server_config: ServerConfig | None = None,
    ) -> None:
        self.stop_event = stop_event
        self.metrics_store = metrics_store
        self.server_config = server_config or get_server_config()

    def run_forever(self) -> None:
        """Run scans on the configured interval until stop_event is set."""
        LOGGER.info(
            "Shared ingest scanner started root=%s interval_seconds=%s",
            self.server_config.shared_ingest_dir,
            self.server_config.shared_ingest_scan_interval_seconds,
        )
        while not self.stop_event.is_set():
            try:
                self.scan_once()
            except Exception:
                LOGGER.exception("Shared ingest scan failed")
            self.stop_event.wait(
                self.server_config.shared_ingest_scan_interval_seconds
            )

    def scan_once(self) -> int:
        """Create missing collection folders and enqueue changed input files once."""
        if not self.server_config.shared_ingest_enabled:
            return 0

        root = self.server_config.shared_ingest_dir
        root.mkdir(parents=True, exist_ok=True)
        self._ensure_collection_folders()

        queued = 0
        for collection_dir in sorted(root.iterdir()):
            if not self._is_collection_dir(collection_dir):
                continue
            collection_name = canonical_collection_name(
                collection_dir.name,
                self.server_config,
            )
            output_dir = collection_dir / OUTPUT_DIR_NAME
            output_dir.mkdir(parents=True, exist_ok=True)
            state = self._load_state(output_dir)
            state_changed = False

            for path in sorted(collection_dir.iterdir()):
                if not self._is_candidate_file(path):
                    continue
                identity = self._file_identity(path)
                previous = self._state_files(state).get(path.name)
                if previous and previous.get("identity") == identity:
                    continue
                if not self._is_stable(path):
                    continue

                job = self._build_job(path, collection_name, identity)
                self.metrics_store.create_for_job(job)
                self.metrics_store.update(
                    job.job_id,
                    collection_name=collection_name,
                    task_id=job.input_data.get("task_id"),
                    document_metadata=job.input_data.get("document_metadata") or {},
                    deleted=False,
                )
                local_queue.put(job)
                self._state_files(state)[path.name] = {
                    "identity": identity,
                    "job_id": job.job_id,
                    "status": "queued",
                    "queued_at": time(),
                }
                state_changed = True
                queued += 1
                LOGGER.info(
                    "Queued shared ingest file path=%s job_id=%s collection=%s",
                    path,
                    job.job_id,
                    collection_name,
                )

            if state_changed:
                self._write_state(output_dir, state)

        return queued

    def _ensure_collection_folders(self) -> None:
        collection_names = {self.server_config.elastic_index_name}
        collection_names.update(self._elastic_collection_names())
        for collection_name in collection_names:
            output_dir = shared_output_dir_for_collection(
                collection_name,
                self.server_config,
            )
            output_dir.mkdir(parents=True, exist_ok=True)

    def _elastic_collection_names(self) -> set[str]:
        if not self.server_config.elastic_hosts:
            return set()
        try:
            from elasticsearch import Elasticsearch
        except ImportError:
            LOGGER.warning(
                "Elasticsearch client is unavailable; skipping shared folder sync."
            )
            return set()

        client = Elasticsearch(
            hosts=self.server_config.elastic_hosts,
            api_key=self.server_config.elastic_api_key,
            verify_certs=self.server_config.elastic_verify_certs,
            ssl_show_warn=self.server_config.elastic_ssl_show_warn,
            http_compress=self.server_config.elastic_http_compress,
        )
        try:
            response = client.indices.get_mapping(
                index=f"{OPEN_RAG_PREFIX}*",
                expand_wildcards="open",
                ignore_unavailable=True,
            )
        except Exception as exc:
            LOGGER.warning("Failed to sync shared folders from Elasticsearch: %s", exc)
            return set()
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

        body = getattr(response, "body", response)
        if not isinstance(body, dict):
            return set()
        return {
            str(index_name)
            for index_name in body
            if str(index_name).startswith(OPEN_RAG_PREFIX)
        }

    @staticmethod
    def _is_collection_dir(path: Path) -> bool:
        return (
            path.is_dir()
            and not path.name.startswith(".")
            and path.name != OUTPUT_DIR_NAME
        )

    @staticmethod
    def _is_candidate_file(path: Path) -> bool:
        if not path.is_file() or path.name.startswith("."):
            return False
        return not path.name.lower().endswith(_TEMP_SUFFIXES)

    def _is_stable(self, path: Path) -> bool:
        stable_seconds = self.server_config.shared_ingest_stable_seconds
        if stable_seconds <= 0:
            return True
        return time() - path.stat().st_mtime >= stable_seconds

    @staticmethod
    def _file_identity(path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {
            "path": str(path.resolve()),
            "mtime_ns": stat.st_mtime_ns,
            "size_bytes": stat.st_size,
        }

    @staticmethod
    def _state_files(state: dict[str, Any]) -> dict[str, Any]:
        files = state.get("files")
        if not isinstance(files, dict):
            files = {}
            state["files"] = files
        return files

    @staticmethod
    def _load_state(output_dir: Path) -> dict[str, Any]:
        state_path = output_dir / STATE_FILE_NAME
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {"files": {}}
        return payload if isinstance(payload, dict) else {"files": {}}

    @staticmethod
    def _write_state(output_dir: Path, state: dict[str, Any]) -> None:
        state_path = output_dir / STATE_FILE_NAME
        temp_path = output_dir / f"{STATE_FILE_NAME}.tmp"
        temp_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(state_path)

    def _build_job(
        self,
        path: Path,
        collection_name: str,
        identity: dict[str, Any],
    ) -> Job:
        task_id = uuid4().hex
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        metadata = {
            "shared_ingest_path": str(path),
            "shared_ingest_collection": path.parent.name,
        }
        return Job.create(
            parser_type="docling",
            input_data={
                "source": "shared-folder",
                "file_name": path.name,
                "file_path": str(path),
                "mime_type": mime_type,
                "size_bytes": identity["size_bytes"],
                "collection_name": collection_name,
                "task_id": task_id,
                "document_metadata": metadata,
            },
            chunker_type="token",
            settings={
                "queue": self.server_config.inbound_queue_name,
                "elastic_index_name": collection_name,
                "collection_name": collection_name,
            },
        )


def update_shared_ingest_state(
    job: Job,
    status: str,
    *,
    error: str | None = None,
) -> bool:
    if job.input_data.get("source") != "shared-folder":
        return False

    file_path_value = job.input_data.get("file_path")
    if not file_path_value:
        return False

    file_path = Path(str(file_path_value))
    output_dir = file_path.parent / OUTPUT_DIR_NAME
    try:
        state = SharedFolderScanner._load_state(output_dir)
        entry = SharedFolderScanner._state_files(state).get(file_path.name)
        if not isinstance(entry, dict) or entry.get("job_id") != job.job_id:
            return False

        entry["status"] = status
        entry["updated_at"] = time()
        if error:
            entry["error"] = error
        else:
            entry.pop("error", None)
        SharedFolderScanner._write_state(output_dir, state)
    except OSError as exc:
        LOGGER.warning("Failed to update shared ingest state job_id=%s: %s", job.job_id, exc)
        return False
    return True
