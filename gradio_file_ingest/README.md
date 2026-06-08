# Gradio File Ingest

Standalone Gradio frontend for posting uploaded files to the existing file ingest endpoint.

## Run

```bash
cd gradio_file_ingest
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

The app defaults to `http://127.0.0.1:8000/api/v1/ingest/file`.

Optional environment variables:

- `INGEST_API_URL`: backend base URL.
- `INGEST_FILE_PATH`: backend ingest path.
- `INGEST_JOBS_PATH`: backend jobs metrics path.
- `INGEST_POLL_SECONDS`: polling interval for the jobs dashboard.
- `INGEST_TIMEOUT_SECONDS`: request timeout per file.
- `GRADIO_SERVER_NAME`: Gradio bind host.
- `GRADIO_SERVER_PORT`: Gradio port.

Files are posted as multipart form data with field name `file` and form value `source=gradio`.
The dashboard polls the backend jobs endpoint and shows queued/running, processed, and failed jobs.
