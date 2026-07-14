FROM python:3.12-slim

  ENV PYTHONDONTWRITEBYTECODE=1 \
      PYTHONUNBUFFERED=1 \
      PIP_NO_CACHE_DIR=1 \
      PYTHONPATH=/app/src/ingest-server-orquestator:/app \
      HOME=/home/ingest \
      USER=ingest \
      LOGNAME=ingest \
      XDG_CACHE_HOME=/home/ingest/.cache \
      TORCHINDUCTOR_CACHE_DIR=/home/ingest/.cache/torchinductor

  WORKDIR /app

  RUN apt-get update && \
      apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libsm6 \
        libxext6 \
        libxrender1 \
        passwd && \
      rm -rf /var/lib/apt/lists/*

  # Crear una identidad Unix real para el UID/GID usado por Kubernetes.
  RUN useradd \
        --uid 2000 \
        --gid 0 \
        --home-dir /home/ingest \
        --create-home \
        --shell /usr/sbin/nologin \
        ingest

  COPY ingest-server-orquestator/requirements.txt \
       ingest-server-orquestator/constraints.txt \
       ./

  RUN python -m pip install --upgrade pip && \
      python -m pip install -r requirements.txt && \
      python -m pip install --no-deps surya-ocr==0.20.0

  # El código permanece propiedad de root y solo necesita ser legible.
  COPY ingest-server-orquestator/src ./src

  # Directorios que la aplicación puede necesitar escribir.
  RUN mkdir -p \
        /home/ingest/.cache/torchinductor \
        /uploads \
        /outputs \
        /tokenizer \
        /docling-models && \
      chown -R 2000:0 \
        /home/ingest \
        /uploads \
        /outputs \
        /tokenizer \
        /docling-models && \
      chmod -R u=rwX,g=rwX,o= \
        /home/ingest \
        /uploads \
        /outputs \
        /tokenizer \
        /docling-models

  USER 2000:0

  EXPOSE 8000

  CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
