# Documentation Index

Use these documents as the maintained project docs.

## Start Here

- `python-class-guide.md`: class-by-class guide for the Python ingest service.
- `ingest-server-pipeline-workflow.md`: runtime flow from upload or shared
  folder ingest through Docling, chunking, Elasticsearch, and RAG retrieval.

## Operations

- `k3s-airgapped-deployment.md`: build, image import, model layout, mounts, and
  offline k3s deployment notes.
- `ingest-server-kubernetes-architecture.md`: cluster architecture snapshot.
  Treat concrete live counts, versions, IPs, and pod states as examples that can
  drift from the checked-in manifests.

## RAG Artifacts

- `../elastic_integration/rag-AGENT.md`: Agent Builder instruction text.
- `../elastic_integration/rag-agent-builder-skill.md`: compact Agent Builder
  skill text.
- `../elastic_integration/rag-workflow.yml`: current checked-in RAG workflow.
- `../elastic_integration/rag-workflow-v2.yml`: alternate workflow artifact kept
  for comparison/tests.

Removed docs:

- `4. Workflow RAG.md` was deleted because it duplicated
  `ingest-server-pipeline-workflow.md` and described obsolete lexical/page
  fields that no longer match the current workflow and index contract.
