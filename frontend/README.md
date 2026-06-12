# Ingest Server Frontend

React/Vite frontend adapted from the NVIDIA RAG Blueprint frontend:

https://github.com/NVIDIA-AI-Blueprints/rag/tree/main/frontend

The app keeps the NVIDIA collection, upload, task notification, settings, and
chat surfaces. This repository's FastAPI backend provides a compatibility
adapter for the frontend under `/api/*`.

## Run Locally

```bash
cd frontend
npm install
VITE_INGEST_API_URL=http://localhost:8000 npm run dev
```

Open `http://localhost:3000`.

## API Contract

The Vite dev server proxies `/api/*` to `VITE_INGEST_API_URL`, defaulting to
`http://localhost:8000`.

Primary endpoints used by the frontend:

- `GET /api/health`
- `GET /api/configuration`
- `GET /api/collections`
- `POST /api/collection`
- `POST /api/documents?blocking=false`
- `GET /api/documents?collection_name=<name>`
- `GET /api/status?task_id=<task_id>`
- `GET /api/summary?collection_name=<name>&file_name=<name>`
- `POST /api/generate`

`POST /api/generate` uses the NVIDIA streaming response shape, but this backend
does not include a RAG generation service. It returns an adapter status response
so the chat surface fails gracefully without a separate generation backend.

## Build

```bash
npm run build
npm run serve
```

For containers, build from this directory:

```bash
docker build -t ingest-server-orquestator-frontend:latest .
docker run --rm -p 3000:3000 -e INGEST_API_URL=http://host.docker.internal:8000 ingest-server-orquestator-frontend:latest
```
