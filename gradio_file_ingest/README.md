# Gradio File Ingest

Standalone Gradio frontend for posting uploaded files to the file ingest API.

In Docker and k3s deployments, Gradio runs as an independent container or pod
and talks to the internal ingest API service:

```text
http://<gradio-host>:7860
```

## Run

```bash
cd gradio_file_ingest
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

The app posts files to `/api/v1/ingest/file` and polls job metrics from
`/api/v1/ingest/jobs`.

Optional environment variables for embedded and standalone runs:

- `INGEST_API_URL`: backend base URL.
- `INGEST_POLL_SECONDS`: polling interval for the jobs dashboard.
- `INGEST_TIMEOUT_SECONDS`: request timeout per file.
- `GRADIO_ROOT_PATH`: root path when serving behind a reverse proxy.

Files are posted as multipart form data with field name `file` and form value `source=gradio`.
The dashboard polls the backend jobs endpoint and shows queued/running, processed, and failed jobs.
