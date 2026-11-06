# Embeddings

This document is written solely by Shi Quan. No LLM was involved.

## Features

* CLI-based ingestion
* Configurable parameters
  * strategy (fixed, fixed_overlap, heading_aware)
  * tokens
  * overlap
* Idempotent ingestion
* Ingestion status tracking
* Embedding generation runs are recorded via run ID

## Embedding configuration

| Component      | Value                      |
| -------------- | -------------------------- |
| Model          | `text-embedding-3-small` |
| Dimensions     | 1536                       |
| Tokenizer      | `cl100k_base`            |
| Database       | Supabase PostgreSQL        |
| Vector storage | pgvector                   |

## Workflow

1. Markdown files
2. Markdown parser
3. Generate chunks
4. Generate embeddings (OpenAI)
5. Store chunks and embeddings (PostgreSQL)

## CLI Usage

```Shell
# Fixed
uv run python -m app.functions.ingest_handbook \
  --strategy fixed \
  --max-tokens 200 \
  --overlap-tokens 0

# Fixed + overlap
uv run python -m app.functions.ingest_handbook \
  --strategy fixed_overlap \
  --max-tokens 200 \
  --overlap-tokens 40

# Heading-aware
uv run python -m app.functions.ingest_handbook \
  --strategy heading_aware \
  --max-tokens 200 \
  --overlap-tokens 40
```

## SQL Schema

| col1                        | col2                                                                                                                                                                                                                              |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `knowledge_documents`     | Stores information about each handbook. <br />- file path<br />- content hash to track changes                                                                                                                                   |
| `ingestion_runs`          | Each ingestion run is saved with the following details:<br />- strategy<br />- tokens<br />- overlap tokens<br />- embedding model<br />- status of the ingestion<br />- snapshot_fingerprint to prevent duplicate ingestion runs |
| `ingestion_run_documents` | Records which source document versions belong to each run                                                                                                                                                                         |
| `knowledge_chunks`        | Stores chunks, metadata and embedding vectors                                                                                                                                                                                     |
