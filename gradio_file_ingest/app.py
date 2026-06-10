from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any

import gradio as gr
import requests


DEFAULT_BACKEND_URL = os.getenv("INGEST_API_URL", "http://127.0.0.1:8000")
INGEST_FILE_ENDPOINT = "/api/v1/ingest/file"
INGEST_JOBS_ENDPOINT = "/api/v1/ingest/jobs"
GRADIO_SERVER_NAME = "0.0.0.0"
GRADIO_SERVER_PORT = 7860
POLL_SECONDS = float(os.getenv("INGEST_POLL_SECONDS", "3"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("INGEST_TIMEOUT_SECONDS", "60"))

ACTIVE_HEADERS = [
    "File",
    "Status",
    "Stage",
    "Pages",
    "Chunks",
    "Elapsed",
    "Slowest",
    "Rate",
    "Message",
    "Updated",
]
PROCESSED_HEADERS = [
    "File",
    "Status",
    "Pages",
    "Chunks",
    "Elapsed",
    "Slowest",
    "Rate",
    "Finished",
    "Message",
]
ERROR_HEADERS = ["File", "Stage", "Pages", "Elapsed", "Slowest", "Error", "Finished"]


def _target_url(base_url: str, endpoint_path: str) -> str:
    base = (base_url or DEFAULT_BACKEND_URL).strip().rstrip("/")
    endpoint = endpoint_path.strip()
    if not endpoint.startswith("/"):
        endpoint = f"/{endpoint}"
    return f"{base}{endpoint}"


def _jobs_url(base_url: str) -> str:
    return _target_url(base_url, INGEST_JOBS_ENDPOINT)


def _uploaded_path(uploaded_file: Any) -> Path:
    if isinstance(uploaded_file, (str, Path)):
        return Path(uploaded_file)

    if isinstance(uploaded_file, dict):
        for key in ("path", "name"):
            value = uploaded_file.get(key)
            if value:
                return Path(value)

    file_name = getattr(uploaded_file, "name", None)
    if file_name:
        return Path(file_name)

    path = getattr(uploaded_file, "path", None)
    if path:
        return Path(path)

    raise ValueError("Could not resolve uploaded file path")


def _uploaded_file_name(uploaded_file: Any, path: Path) -> str:
    if isinstance(uploaded_file, dict):
        for key in ("orig_name", "original_name", "filename"):
            value = uploaded_file.get(key)
            if value:
                return Path(str(value).replace("\\", "/")).name

    for attr in ("orig_name", "original_name", "filename"):
        value = getattr(uploaded_file, attr, None)
        if value:
            return Path(str(value).replace("\\", "/")).name

    return path.name


def _uploaded_mime_type(uploaded_file: Any, file_name: str) -> str:
    if isinstance(uploaded_file, dict):
        for key in ("mime_type", "content_type"):
            value = uploaded_file.get(key)
            if value:
                return str(value)

    for attr in ("mime_type", "content_type"):
        value = getattr(uploaded_file, attr, None)
        if value:
            return str(value)

    return mimetypes.guess_type(file_name)[0] or "application/octet-stream"


def _uploaded_files(uploaded_files: Any) -> list[Any]:
    if uploaded_files is None:
        return []
    if isinstance(uploaded_files, list):
        return uploaded_files
    if isinstance(uploaded_files, tuple):
        return list(uploaded_files)
    return [uploaded_files]


def _response_body(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _jobs_from_response(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, dict):
        jobs = body.get("jobs")
        if isinstance(jobs, list):
            return [job for job in jobs if isinstance(job, dict)]
    if isinstance(body, list):
        return [job for job in body if isinstance(job, dict)]
    return []


def _pages_text(job: dict[str, Any]) -> str:
    processed = int(job.get("pages_processed") or 0)
    total = job.get("total_pages")
    if total is None:
        return f"{processed}/?"
    return f"{processed}/{total}"


def _chunks_text(job: dict[str, Any]) -> str:
    created = int(job.get("chunks_created") or 0)
    dispatched = int(job.get("chunks_dispatched") or 0)
    return f"{dispatched}/{created}"


def _seconds_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.1f}s"
    except (TypeError, ValueError):
        return ""


def _rate_text(job: dict[str, Any]) -> str:
    pages_per_second = job.get("pages_per_second")
    chunks_per_second = job.get("chunks_per_second")
    parts = []
    try:
        if pages_per_second is not None:
            parts.append(f"{float(pages_per_second):.2f} p/s")
    except (TypeError, ValueError):
        pass
    try:
        if chunks_per_second is not None:
            parts.append(f"{float(chunks_per_second):.2f} c/s")
    except (TypeError, ValueError):
        pass
    return ", ".join(parts)


def _active_row(job: dict[str, Any]) -> list[Any]:
    return [
        job.get("file_name") or "",
        job.get("status") or "",
        job.get("stage") or "",
        _pages_text(job),
        _chunks_text(job),
        _seconds_text(job.get("elapsed_seconds")),
        job.get("slowest_stage") or "",
        _rate_text(job),
        job.get("message") or "",
        job.get("updated_at") or "",
    ]


def _processed_row(job: dict[str, Any]) -> list[Any]:
    return [
        job.get("file_name") or "",
        job.get("status") or "",
        _pages_text(job),
        _chunks_text(job),
        _seconds_text(job.get("elapsed_seconds")),
        job.get("slowest_stage") or "",
        _rate_text(job),
        job.get("finished_at") or "",
        job.get("message") or "",
    ]


def _error_row(job: dict[str, Any]) -> list[Any]:
    return [
        job.get("file_name") or "",
        job.get("stage") or "",
        _pages_text(job),
        _seconds_text(job.get("elapsed_seconds")),
        job.get("slowest_stage") or "",
        job.get("error") or "",
        job.get("finished_at") or "",
    ]


def _job_tables(
    jobs: list[dict[str, Any]],
) -> tuple[str, list[list[Any]], list[list[Any]], list[list[Any]]]:
    active_jobs = [
        job for job in jobs if job.get("status") not in {"done", "failed"}
    ]
    processed_jobs = [job for job in jobs if job.get("status") == "done"]
    error_jobs = [job for job in jobs if job.get("status") == "failed"]
    summary = (
        f"Jobs: {len(jobs)} total, {len(active_jobs)} active, "
        f"{len(processed_jobs)} done, {len(error_jobs)} failed."
    )
    return (
        summary,
        [_active_row(job) for job in active_jobs],
        [_processed_row(job) for job in processed_jobs],
        [_error_row(job) for job in error_jobs],
    )


def fetch_job_metrics(
    backend_url: str,
) -> tuple[str, list[list[Any]], list[list[Any]], list[list[Any]]]:
    url = _jobs_url(backend_url)
    try:
        response = requests.get(
            url,
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return f"Could not load job metrics from `{url}`: {exc}", [], [], []

    return _job_tables(_jobs_from_response(_response_body(response)))


def post_files(uploaded_files: Any, backend_url: str) -> tuple[str, list[dict[str, Any]]]:
    files = _uploaded_files(uploaded_files)
    if not files:
        return "No files selected.", []

    url = _target_url(backend_url, INGEST_FILE_ENDPOINT)
    results: list[dict[str, Any]] = []

    for uploaded_file in files:
        try:
            path = _uploaded_path(uploaded_file)
        except ValueError as exc:
            results.append({"ok": False, "error": str(exc)})
            continue

        if not path.is_file():
            results.append(
                {
                    "file": path.name,
                    "ok": False,
                    "error": f"File does not exist: {path}",
                }
            )
            continue

        file_name = _uploaded_file_name(uploaded_file, path)
        content_type = _uploaded_mime_type(uploaded_file, file_name)
        size_bytes = path.stat().st_size

        try:
            with path.open("rb") as file_handle:
                response = requests.post(
                    url,
                    data={"source": "gradio"},
                    files={"file": (file_name, file_handle, content_type)},
                    headers={"Accept": "application/json"},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
        except requests.RequestException as exc:
            results.append(
                {
                    "file": file_name,
                    "size_bytes": size_bytes,
                    "ok": False,
                    "error": str(exc),
                }
            )
            continue

        results.append(
            {
                "file": file_name,
                "size_bytes": size_bytes,
                "ok": response.ok,
                "status_code": response.status_code,
                "response": _response_body(response),
            }
        )

    successful = sum(1 for result in results if result.get("ok"))
    total = len(results)

    if successful == total:
        status = f"Posted {successful}/{total} file(s) to `{url}`."
    elif successful == 0:
        status = f"Posted 0/{total} file(s)."
    else:
        status = f"Posted {successful}/{total} file(s); review failed responses."

    return status, results


def post_files_and_refresh(
    uploaded_files: Any,
    backend_url: str,
) -> tuple[
    str,
    list[dict[str, Any]],
    str,
    list[list[Any]],
    list[list[Any]],
    list[list[Any]],
]:
    status, results = post_files(uploaded_files, backend_url)
    summary, active_rows, processed_rows, error_rows = fetch_job_metrics(backend_url)
    return status, results, summary, active_rows, processed_rows, error_rows


def clear_outputs() -> tuple[None, str, None]:
    return None, "", None


def build_app() -> gr.Blocks:
    with gr.Blocks(title="File Ingest") as app:
        gr.Markdown("# File Ingest")

        backend_url = gr.Textbox(label="Backend URL", value=DEFAULT_BACKEND_URL)

        uploaded_files = gr.File(
            label="Files",
            file_count="multiple",
            type="filepath",
        )

        with gr.Row():
            submit = gr.Button("Post files", variant="primary")
            clear = gr.Button("Clear")

        status = gr.Markdown()
        responses = gr.JSON(label="Responses")
        metrics_summary = gr.Markdown()
        active_jobs = gr.Dataframe(
            headers=ACTIVE_HEADERS,
            datatype=["str"] * len(ACTIVE_HEADERS),
            interactive=False,
            label="Queue and running",
        )
        processed_jobs = gr.Dataframe(
            headers=PROCESSED_HEADERS,
            datatype=["str"] * len(PROCESSED_HEADERS),
            interactive=False,
            label="Processed",
        )
        failed_jobs = gr.Dataframe(
            headers=ERROR_HEADERS,
            datatype=["str"] * len(ERROR_HEADERS),
            interactive=False,
            label="Errors",
        )
        timer = gr.Timer(value=POLL_SECONDS)

        submit.click(
            fn=post_files_and_refresh,
            inputs=[uploaded_files, backend_url],
            outputs=[
                status,
                responses,
                metrics_summary,
                active_jobs,
                processed_jobs,
                failed_jobs,
            ],
        )
        clear.click(
            fn=clear_outputs,
            outputs=[uploaded_files, status, responses],
        )
        timer.tick(
            fn=fetch_job_metrics,
            inputs=[backend_url],
            outputs=[metrics_summary, active_jobs, processed_jobs, failed_jobs],
        )

    return app


if __name__ == "__main__":
    root_path = os.getenv("GRADIO_ROOT_PATH") or None
    build_app().launch(
        server_name=GRADIO_SERVER_NAME,
        server_port=GRADIO_SERVER_PORT,
        root_path=root_path,
    )
