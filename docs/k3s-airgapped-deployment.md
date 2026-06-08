# k3s Air-Gapped Deployment

This service is designed to run without downloading models at runtime. Kubernetes
mounts provide the model folders, and the application uses stable container paths.

## Container Path Contract

The app expects these paths inside the container:

| Container path | Purpose | Access |
| --- | --- | --- |
| `/uploads` | Uploaded input files | Read/write |
| `/outputs` | Generated markdown outputs | Read/write |
| `/tokenizer` | Tokenizer folder used by chunking | Read-only |
| `/docling-models/artifacts` | Docling model artifacts | Read-only |
| `/docling-models/models/MinerU2.5-Pro-2605-1.2B` | MinerU OCR model folder | Read-only |
| `/docling-models/pp-doclayout-v3` | PP-DocLayoutV3 Hugging Face model folder | Read-only |

Do not configure these paths with environment variables. Select the actual host
folders using PV/PVC mounts and `subPath`.

## Expected Host Layout

For a local PV rooted at `/datastore/models`, use:

```text
/datastore/models/
  docling/
    artifacts/
    models/
      MinerU2.5-Pro-2605-1.2B/
    pp-doclayout-v3/
  tokenizers/
    qwen3-embedding-4b/
```

For ingest data, use one writable PV/PVC and subpaths:

```text
/datastore/ingest/
  uploads/
  outputs/
```

## Build And Export The Application Image

Build the Docker image on a machine that has network access to install Python
dependencies. The build context must be the parent directory of this repository,
because the Dockerfile copies `ingest-server-orquestator/...` paths:

```bash
cd /datastore/experimento-101
docker build \
  -f ingest-server-orquestator/Dockerfile \
  -t ingest-server-orquestator:latest \
  .
```

If you are already inside the repository directory, use the parent directory as
the build context:

```bash
docker build -f Dockerfile -t ingest-server-orquestator:latest ..
```

The tag must match the image referenced by `k8s/ingest-server.yaml`:

```yaml
image: ingest-server-orquestator:latest
imagePullPolicy: IfNotPresent
```

Export the image as a tarball for the air-gapped k3s node:

```bash
docker save ingest-server-orquestator:latest \
  | gzip -c > ingest-server-orquestator_latest.tar.gz
sha256sum ingest-server-orquestator_latest.tar.gz \
  > ingest-server-orquestator_latest.tar.gz.sha256
```

Copy `ingest-server-orquestator_latest.tar.gz` and its `.sha256` file to every
k3s node that can schedule the ingest pod.

## Import The Image Into k3s

On each air-gapped k3s node, verify and import the image into k3s containerd:

```bash
sha256sum -c ingest-server-orquestator_latest.tar.gz.sha256
gunzip -k ingest-server-orquestator_latest.tar.gz
sudo k3s ctr -n k8s.io images import ingest-server-orquestator_latest.tar
sudo k3s crictl images | grep ingest-server-orquestator
```

Apply the manifest after the image and model folders are present:

```bash
kubectl apply -f k8s/ingest-server.yaml
kubectl rollout status deployment/ingest-server
```

If you import a new build using the same `ingest-server-orquestator:latest` tag,
restart the deployment so k3s creates a new pod from the newly imported image:

```bash
kubectl rollout restart deployment/ingest-server
kubectl rollout status deployment/ingest-server
```

The API application listens on port `8000`, and the API service is `ClusterIP`
only. Do not expose the `ingest-server` service outside the cluster. The
manifest also includes a NetworkPolicy that allows API ingress on port `8000`
from the Gradio pod only, when network policy enforcement is enabled in k3s.

Gradio runs as a separate pod in the same manifest and talks to the internal API
service at `http://ingest-server:8000`.

```text
http://<ingest-gradio-service>:7860
```

The Gradio pod uses these ConfigMap values:

```yaml
data:
  INGEST_API_URL: http://ingest-server:8000
  INGEST_POLL_SECONDS: "3"
  INGEST_TIMEOUT_SECONDS: "60"
  GRADIO_ROOT_PATH: ""
```

The upload and jobs endpoints are fixed in code as `/api/v1/ingest/file` and
`/api/v1/ingest/jobs`.

For local access without exposing the API service, port-forward only Gradio:

```bash
kubectl port-forward svc/ingest-gradio 7860:7860
```

## GPU Selection In k3s

The k3s manifest does not request `nvidia.com/gpu`. Instead, it forces the
visible host GPU through `NVIDIA_VISIBLE_DEVICES` in the `ingest-server-config`
ConfigMap. Set `X` to the host GPU id you want the pod to use:

```yaml
data:
  NVIDIA_VISIBLE_DEVICES: "X"
```

`NVIDIA_VISIBLE_DEVICES` controls which host GPU is exposed to the container,
and the app uses logical CUDA device `0` inside the container.

## k3s Mounts

Example API pod mounts:

```yaml
volumeMounts:
  - name: ingest-data
    mountPath: /uploads
    subPath: uploads
  - name: ingest-data
    mountPath: /outputs
    subPath: outputs
  - name: models-llm
    mountPath: /tokenizer
    subPath: tokenizers/qwen3-embedding-4b
    readOnly: true
  - name: models-llm
    mountPath: /docling-models
    subPath: docling
    readOnly: true

volumes:
  - name: ingest-data
    persistentVolumeClaim:
      claimName: ingest-data-pvc
  - name: models-llm
    persistentVolumeClaim:
      claimName: models-llm-pvc
      readOnly: true
```

To use a different tokenizer, change only the tokenizer `subPath`:

```yaml
subPath: tokenizers/another-tokenizer-folder
```

## Runtime Offline Behavior

The application sets these internally before Docling and Transformers load:

```env
DOCLING_ARTIFACTS_PATH=/docling-models/artifacts
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

Docling receives `artifacts_path=/docling-models/artifacts`. The custom
PP-DocLayout model is loaded from `/docling-models/pp-doclayout-v3`.

If a required model is missing, the app should fail locally instead of trying to
download it from the internet.

OCR is configured through the `ingest-server-config` ConfigMap. The default is
offline EasyOCR with Spanish and English:

```env
DOCLING_OCR_ENABLED=true
DOCLING_OCR_ENGINE=easyocr
DOCLING_OCR_LANGS=es,en
DOCLING_MINERU_DEVICE=auto
DOCLING_MINERU_DTYPE=auto
DOCLING_MINERU_BATCH_SIZE=1
DOCLING_MINERU_IMAGE_ANALYSIS=false
DOCLING_FORCE_FULL_PAGE_OCR=false
DOCLING_OCR_BITMAP_AREA_THRESHOLD=0.05
DOCLING_OCR_BATCH_SIZE=8
DOCLING_LAYOUT_BATCH_SIZE=4
DOCLING_TABLE_BATCH_SIZE=8
DOCLING_QUEUE_MAX_SIZE=16
```

This expects EasyOCR artifacts under `/docling-models/artifacts/EasyOcr`.
The default EasyOCR path runs OCR on CPU so GPU memory is reserved for layout
and VLM stages.
`DOCLING_OCR_ENGINE=mineru` is available for MinerU OCR and expects the model
under `/docling-models/models/MinerU2.5-Pro-2605-1.2B`. The MinerU adapter uses
the pinned Transformers dependency from this project; do not install
`mineru-vl-utils[transformers]`, because that extra requires a different
Transformers major version. `DOCLING_OCR_ENGINE=rapidocr` is also available for
RapidOCR, but in this Docling version RapidOCR language support is limited to
`english` and `chinese`.
Use `DOCLING_OCR_ENABLED=false` for digitally native PDFs when OCR adds noise or
runtime without improving extraction.

Docling layout and enrichment are GPU-heavy. Keep the API worker at one
concurrent parser process unless the selected GPU has enough free memory for
multiple PP-DocLayout/CodeFormula pipelines:

```env
INGEST_WORKER_MAX_WORKERS=1
```

Increasing `INGEST_WORKER_MAX_WORKERS` can improve throughput, but multiple
concurrent jobs can produce CUDA out-of-memory failures even on large GPUs when
other processes are already using VRAM. If memory pressure still appears with a
single worker, lower `DOCLING_LAYOUT_BATCH_SIZE` first.

## Download Models On An Internet-Connected Machine

Install the same project dependencies or at least Docling, MinerU utilities, and
Hugging Face tools:

```bash
python -m venv .venv
source .venv/bin/activate
pip install docling mineru-vl-utils==1.0.4 huggingface_hub
```

Create the target model layout:

```bash
mkdir -p /datastore/models/docling/artifacts
mkdir -p /datastore/models/docling/models/MinerU2.5-Pro-2605-1.2B
mkdir -p /datastore/models/docling/pp-doclayout-v3
mkdir -p /datastore/models/tokenizers/qwen3-embedding-4b
```

Download Docling's predefined model set:

```bash
docling-tools models download \
  --output-dir /datastore/models/docling/artifacts
```

For every Docling-managed optional model available through the CLI:

```bash
docling-tools models download --all \
  --output-dir /datastore/models/docling/artifacts
```

Download the PP-DocLayoutV3 Hugging Face repository into the exact folder the app
mounts:

```bash
huggingface-cli download PaddlePaddle/PP-DocLayoutV3_safetensors \
  --local-dir /datastore/models/docling/pp-doclayout-v3 \
  --local-dir-use-symlinks False
```

Download the MinerU OCR model into the exact folder the app mounts:

```bash
huggingface-cli download opendatalab/MinerU2.5-Pro-2605-1.2B \
  --local-dir /datastore/models/docling/models/MinerU2.5-Pro-2605-1.2B \
  --local-dir-use-symlinks False
```

Download the tokenizer folder used by the current deployment:

```bash
huggingface-cli download Qwen/Qwen3-Embedding-4B \
  --local-dir /datastore/models/tokenizers/qwen3-embedding-4b \
  --local-dir-use-symlinks False
```

If the tokenizer comes from another source, place that tokenizer's complete
folder under `/datastore/models/tokenizers/<name>` and point the k3s `subPath`
at that folder.

## Move Models Into The Air-Gapped Node

Package the prepared model tree:

```bash
tar -C /datastore -czf models-airgap.tar.gz models
```

Copy `models-airgap.tar.gz` to the k3s node and extract it:

```bash
sudo mkdir -p /datastore
sudo tar -C /datastore -xzf models-airgap.tar.gz
```

Verify the required folders exist:

```bash
test -d /datastore/models/docling/artifacts
test -d /datastore/models/docling/models/MinerU2.5-Pro-2605-1.2B
test -d /datastore/models/docling/pp-doclayout-v3
test -d /datastore/models/tokenizers/qwen3-embedding-4b
```

## Important External Model Service

The app uses `PictureDescriptionApiOptions` and calls the service configured by
`DOCLING_PICTURE_DESCRIPTION_URL`, currently:

```env
http://vllm-qwen35-9b:8007/v1/chat/completions
```

That VLM is not downloaded by this app. Provision its model separately for the
vLLM service in the air-gapped cluster.

## References

- Docling advanced options: model prefetching, offline usage, `artifacts_path`,
  and `DOCLING_ARTIFACTS_PATH`: https://docling-project.github.io/docling/usage/advanced_options/
- Docling CLI reference for `docling-tools models download`, `--all`, and
  `download-hf-repo`: https://docling-project.github.io/docling/reference/cli/
- Docling model catalog: https://docling-project.github.io/docling/usage/model_catalog/
- MinerU model: https://huggingface.co/opendatalab/MinerU2.5-Pro-2605-1.2B
