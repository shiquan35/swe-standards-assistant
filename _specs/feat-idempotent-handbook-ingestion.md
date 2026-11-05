# Idempotent Handbook Ingestion and Embeddings

> 🌿 **Branch:** `feat/idempotent-handbook-ingestion` · 📅 **Date:** 2026-11-03

## Problem & Solution
**Problem:** The parser and chunkers produce transient candidates, but there is no embedding or persistence workflow. The current schema groups chunks by run, but cannot identify an exact snapshot or retain each source file's hash for historical runs. Repeated CLI invocations therefore have no defined idempotent behavior.

**Solution:** Add a manual CLI pipeline that reuses the existing parser and chunkers, embeds candidates, and atomically publishes a reproducible handbook snapshot. Reuse an identical completed snapshot and matching stored vectors rather than making duplicate rows or API calls.

## Decisions

| Type | Decision | Choice | Why |
|---|---|---|---|
| Constraint | Parsing/chunking | Reuse `parse_markdown()` and `chunk_document()` and their candidate metadata. Parse the exact captured UTF-8 content used to calculate each raw-byte hash. | Keep parser/chunker boundaries and avoid duplicate logic or hash/content races. |
| Constraint | Vector contract | Use `text-embedding-3-small`, request and validate 1,536 dimensions. | Matches the existing `Vector(1536)` column. |
| Constraint | Migrations | Do not create or edit Alembic migration files; the user generates/applies migrations via CLI. Assume the development `knowledge_chunks` table is empty for the non-null run-FK migration. | Preserves the user's migration workflow; a populated table needs a backfill decision. |
| Choice | Source scope | Recursively ingest sorted `.md` files under `backend/knowledge_base/engineering-handbook`; the README has been moved outside the root. Reject an empty source set. | A whole-handbook snapshot is comparable across runs. |
| Choice | Source identity | Read each discovered file's bytes once; derive its SHA-256 and parsed text from those same bytes. Store repository-relative POSIX paths and retain each file hash per run. | Prevent hashes from describing different bytes than the persisted chunks; preserve historical provenance. |
| Choice | Snapshot identity | Unique SHA-256 over canonical sorted source paths/hashes, strategy/config/model/dimensions, and candidate content/provenance. Recompute parse/chunk output before lookup. | Reuses exact output without a manually bumped chunker version. |
| Choice | Idempotency | No-op for identical completed snapshots; retry a matching failed run row. Enforce unique fingerprint in PostgreSQL. Give each active owner a fresh execution token; guard state changes and final publication by token and `running` status. | Uniqueness prevents duplicate run rows; fencing prevents a stale owner from publishing after retry/recovery. |
| Choice | Embedding reuse | Reuse vectors only from completed runs when exact chunk text and model match; create distinct chunk rows for each run. | Preserves evaluation snapshots while avoiding unnecessary API calls. |
| Choice | Failure atomicity | Publish document updates, run-document mappings, chunks, and completed status in one final transaction. API/publish errors fail the run; parse/chunk errors are logged before run creation. No partial chunks are published. | Prevent incomplete snapshots from appearing complete. |
| Choice | Run timing | Create/reuse a run only after discovery, parsing, and chunking succeed. Earlier failures are logged but have no run row. | Candidate-output fingerprint is needed for exact identity. |
| Choice | Retry cost | Do not checkpoint vectors from failed runs; retries may repeat those calls but can use completed-run cache. | Avoid staging storage and recovery complexity. |
| Choice | Stale workers | Recovery is a separate operation: after operator confirmation, lock the specified run, recheck `running`, mark it `failed`, and clear its token. A later normal ingestion invocation claims the failed run with a fresh token. | Keeps recovery separate from ingestion and fences the old owner before retry. |
| Choice | Current document metadata | `KnowledgeDocument.content_hash` and title represent the last successfully published run for that path, not necessarily current filesystem state. Historical source hashes are authoritative in `ingestion_run_documents`. | Concurrent snapshots may commit out of filesystem order; each run must retain its own provenance. |
| Choice | Embedding requests | Batch sequentially within the API's 2,048-input and 300,000-total-token limits; use bounded OpenAI SDK retries and fail after retries are exhausted. Reject an input above 8,192 tokens; never truncate/split. | Simple rate-limit behavior and exact chunk-to-vector correspondence. |
| Choice | CLI configuration | Require `--strategy`; default max tokens to 200 and overlap to 0 for `fixed`, 40 otherwise. Preserve existing validation, including zero overlap for `fixed`. | Matches current chunk-inspection behavior while making each run's strategy explicit. |
| Choice | Logging/testing | Log run and per-file progress without text, vectors, or credentials. Mock OpenAI in unit tests; use PostgreSQL integration tests. | Useful progress without exposing source content; exercises pgvector/JSONB behavior. |

## Architecture

```text
[ingest_handbook CLI]
        │ strategy + token limits
        ▼
[Pipeline: discover sorted Markdown, capture each file's bytes once,
 hash bytes + decode/parse same capture + chunk with existing module]
         │ candidates + matching source hashes
        ▼
[Canonical snapshot fingerprint]
        │
        ├── completed match ──► [No-op]
        ├── running match ─────► [Refuse]
        └── new or failed run ──► [Normal CLI claims with fresh execution token]
                 │
                 ▼
[Embedding service: completed-run cache by exact text + model]
        │ cache misses, sequential requests packed to API limits
        ▼
[OpenAI embeddings API: text-embedding-3-small, 1536 dims]
        │ ordered vectors
        ▼
[PostgreSQL publish transaction: lock run, verify running + owner token]
        │ only current owner may publish
        ▼
[Atomic snapshot commit]
        ├── ingestion_runs
        ├── ingestion_run_documents (per-run source hashes)
        ├── knowledge_documents (current source hash/title)
        └── knowledge_chunks (run-specific content, metadata, vector)

[recover_ingestion_run CLI] ── operator-confirmed, locked transition ──►
        running run: execution_token set ──► failed run: execution_token cleared
```

## Code Shape

```python
class EmbeddingService:
    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class CapturedSource:
        relative_path: str
        raw_bytes: bytes
        content_hash: str


def ingest_handbook(
    *,
    session: Session,
    source_root: Path,
    strategy: ChunkStrategy,
    config: ChunkingConfig,
    embedder: EmbeddingService,
) -> IngestionResult: ...
```

For each `CapturedSource`, derive `content_hash` from `raw_bytes`, decode those bytes as UTF-8, call `parse_markdown(decoded_text, source_path=relative_path)`, then chunk that parsed value. Never hash and parse by separately rereading the path. `EmbeddingService` is reusable with a one-item sequence for a future retrieval question. Inject the client/service in tests. Persist candidate `heading_paths`, `source_spans`, `parts`, `token_count`, `actual_overlap_tokens`, and `heading_prefix_omitted`; keep the document path and run configuration in their owning records rather than duplicating them in chunk metadata.

## Validation Rules

- `--strategy`: required; one of `fixed`, `fixed_overlap`, `heading_aware`.
- `max_tokens`: positive integer, at most 8,192; default 200.
- `overlap_tokens`: nonnegative and less than `max_tokens`; `fixed` requires 0. Default 0 for `fixed`, 40 otherwise.
- Every embedding input: non-empty and at most 8,192 `cl100k_base` tokens; each request has at most 2,048 inputs and 300,000 aggregate tokens ([OpenAI embeddings API](https://developers.openai.com/api/reference/resources/embeddings/methods/create)). Reject invalid dimensions/counts from the API.
- Source root: fixed at `backend/knowledge_base/engineering-handbook`, resolved relative to the CLI module; recursive `.md` files only, sorted by repository-relative POSIX path. Empty discovery is an error and creates no run.
- `OPENAI_EMBEDDING_MODEL`: must be `text-embedding-3-small`; API key is required only when an uncached embedding request is made.

## Implementation Plan

### Phase 1: Snapshot persistence schema
| File | What changes |
|---|---|
| `backend/app/models/knowledge.py` | Add unique 64-character `snapshot_fingerprint` and nullable UUID `execution_token` to `IngestionRun`, with a check requiring a token while status is `running`; add `IngestionRunDocument` with composite run/document key, source hash, cascades, and relationships. Keep chunks run-specific; run deletion removes its mappings/chunks but not knowledge documents. |

- [ ] Keep schema metadata aligned with the user's CLI-generated migration workflow; do not author migration files.
- [ ] Add PostgreSQL migration-backed coverage for uniqueness, check constraints, foreign keys/cascades, source-hash mappings, and run-delete behavior preserving `KnowledgeDocument` rows. Do not rely solely on `SQLModel.metadata.create_all()`.

### Phase 2: Embedding service
| File | What changes |
|---|---|
| `backend/app/core/env.py` | Add typed optional secret key and fixed model setting; avoid failing app startup when embedding credentials are absent. |
| `backend/app/ingestion/embeddings.py` | Add lazy OpenAI client, sequential requests packed to provider input/token limits, input/dimension/count validation, ordered results, and safe errors. |
| `backend/tests/ingestion/test_embeddings.py` | Test batching/order, singleton calls, input limits, malformed responses, and failures with a fake client. |

- [ ] Confirm `openai` remains the only new runtime dependency; it is already declared in `backend/pyproject.toml`.

### Phase 3: Snapshot pipeline and persistence
| File | What changes |
|---|---|
| `backend/app/ingestion/pipeline.py` | Capture each source's bytes once; derive raw hash and parse from that capture; chunk/fingerprint; atomically claim new/failed runs with a fresh token; reuse completed-run vectors; publish only after locked owner/status verification. |
| `backend/tests/ingestion/test_pipeline.py` | Test stable/changed fingerprints, repeat no-op, captured-byte consistency, per-run hashes, vector reuse, source errors, failed-run retry, fencing rejection, and atomic publication. |
| `backend/tests/ingestion/test_ingestion_postgres.py` | Against a dedicated PostgreSQL database, apply Alembic migrations and inspect the resulting schema; exercise constraints, transaction/row-lock behavior, owner-token fencing, JSONB/vector persistence, uniqueness races, and cascades. |

- [ ] Treat `KnowledgeDocument.content_hash` and title as last-successfully-published metadata only; use `IngestionRunDocument` for historical provenance.
- [ ] Create/claim runs with a fresh `execution_token`; a normal retry transitions `failed` to `running` and assigns a new token under a row lock. Recovery instead transitions `running` to `failed` and clears the token. Require a non-null token for `running` runs. Guard every owner state transition, including marking failure.
- [ ] Insert new runs under the unique fingerprint constraint; on conflict, load and lock the existing row, then branch by its current status (completed: no-op; running: refuse; failed: normal ingestion claims with a fresh token). Never assume a pre-insert lookup prevents a race.
- [ ] In the final transaction, lock the run row (`SELECT ... FOR UPDATE`) and verify `status == running` and the stored token equals the caller's token before writing any snapshot data. Abort on mismatch; keep the row lock through commit.
- [ ] Mark API/publish failures as `failed` only with a conditional owner-token/status check in a separate transaction; a stale worker must not alter a newer owner's state.

### Phase 4: Manual CLI
| File | What changes |
|---|---|
| `backend/app/functions/ingest_handbook.py` | Add `argparse` ingestion entry point with required strategy, token options, fixed source root, and progress/failure exit codes. |
| `backend/app/functions/recover_ingestion_run.py` | Add a separate recovery CLI taking a run UUID; require explicit operator confirmation, lock and recheck that the run is still `running`, then set it to `failed` and clear its execution token. It must not start ingestion. |
| `backend/tests/ingestion/test_ingest_handbook.py` | Test argument defaults/validation, no-source errors, and safe output. |
| `backend/tests/ingestion/test_recover_ingestion_run.py` | Test confirmation, run-not-found/non-running cases, and locked transition to failed with token cleared. |

- [ ] Use the existing module CLI convention; recovery does not ingest. A later normal ingestion command claims a matching failed run with a fresh token. Do not add FastAPI routes or retrieval code.

## Acceptance Criteria

- An identical successful invocation creates no additional run, document, chunk, or embedding API call.
- A run is publishable only while its status is `running` and its stored execution token matches the publisher's token under a row lock; a superseded owner cannot publish or change run status.
- A changed source, candidate output, strategy/configuration, or model produces a distinct fingerprinted run; prior run chunks/embeddings remain available.
- Each run records the raw SHA-256 source hash for every discovered document, including a valid document that yields zero candidates; each hash and parsed/chunked content derive from the same captured bytes.
- `KnowledgeDocument.content_hash` and title mean the last successfully published values for that path; historical source values are read from `IngestionRunDocument`.
- New/changed document rows and all run chunks become visible only after the complete snapshot succeeds; a failure leaves no partial published chunks.
- Identical chunk text/model reuses a vector from a completed run but stores a run-specific chunk row.
- The CLI supports all three existing strategies, enforces token/model limits, reports progress and safe failures, and requires explicit recovery for a stale running row.
- The separate recovery CLI only marks a confirmed, still-running run as failed and clears its token; a subsequent normal ingestion invocation reclaims it with a fresh token.
- Deleting an ingestion run cascades to its chunks and run-document mappings without deleting knowledge documents.
- Unit tests make no live OpenAI calls; PostgreSQL integration tests pass against a migrated disposable database.

## Testing

- Unit-test source discovery, raw-byte SHA-256, canonical fingerprint determinism, each existing chunk strategy, empty discovery, and parser/chunker failure before run creation.
- Fake the OpenAI client to test sequential batches, index ordering, 1,536 dimensions, cache misses/hits, token limits, retries/exhaustion, and safe errors.
- Test completed-run no-op, changed-source/config/output snapshots, failed-run retry, concurrent unique-fingerprint conflict, and no partial rows after failure.
- Test that recovery marks only a still-running specified row failed and clears its token; a subsequent normal invocation claims it with a new token. Verify a prior owner is rejected at publication and cannot alter the new owner's state, and row locking serializes recovery against publication.
- Modify a source file after its bytes are captured but before parsing/publishing; assert the persisted hash and chunks still correspond to the captured version.
- Use a disposable PostgreSQL database selected by `TEST_DATABASE_URL`. Run `alembic upgrade head` against it before integration tests, inspect the actual database schema (columns, unique/check constraints, foreign keys, and cascade rules), then test JSONB/vector persistence, uniqueness, transactions, and cascades. Fail closed if `TEST_DATABASE_URL` is unset; never use the development `DB_FULL_CONNECTION_STRING` or global SQLite `create_all()` fixture as a substitute.

## Logging

| Event | Level | Fields | Example |
|---|---|---|---|
| CLI started | `info` | `invocation_id`, `source_root`, `strategy`, `max_tokens`, `overlap_tokens`, `model` | `{invocation_id: "8c41…", source_root: "knowledge_base/engineering-handbook", strategy: "heading_aware", max_tokens: 200, overlap_tokens: 40, model: "text-embedding-3-small"}` |
| File chunked | `info` | `invocation_id`, `file_path`, `source_hash`, `candidate_count`, `token_total` | `{invocation_id: "8c41…", file_path: "knowledge_base/engineering-handbook/api-standards.md", source_hash: "a93f…", candidate_count: 4, token_total: 1520}` |
| Embedding batch | `debug` | `run_id`, `batch_index`, `model`, `input_count`, `input_tokens`, `dimensions`, `duration_ms` | `{run_id: "6d2b…", batch_index: 1, model: "text-embedding-3-small", input_count: 46, input_tokens: 21240, dimensions: 1536, duration_ms: 820}` |
| Embedding failure | `error` | `run_id`, `model`, `status_code`, `error_code`, `request_id`, `retry_count` | `{run_id: "6d2b…", model: "text-embedding-3-small", status_code: 429, error_code: "rate_limit_exceeded", request_id: "req_…", retry_count: 2}` |
| Snapshot published | `info` | `run_id`, `snapshot_fingerprint`, `status`, `documents`, `chunks`, `cache_hits`, `api_inputs` | `{run_id: "6d2b…", snapshot_fingerprint: "2b7e…", status: "completed", documents: 12, chunks: 46, cache_hits: 8, api_inputs: 38}` |
| Ownership rejected | `warn` | `run_id`, `operation`, `reason`, `status` | `{run_id: "6d2b…", operation: "publish_snapshot", reason: "execution_token_mismatch", status: "running"}` |
| Function entry/exit | `debug` | `function`, safe arguments/result, `duration_ms`, `invocation_id` | `{function: "ingest_handbook", args: {strategy: "fixed_overlap", max_tokens: 200, overlap_tokens: 40}, result: {status: "completed", run_id: "6d2b…"}, duration_ms: 12940, invocation_id: "8c41…"}` |
| Database operation | `debug` | operation name, `run_id`, safe IDs/fingerprint, transaction outcome, row counts | `{operation: "publish_snapshot", run_id: "6d2b…", document_id: "f080…", chunk_index: 3, outcome: "committed", affected_rows: 1}` |

Never log chunk text, embedding vectors, API keys, or bound DB values containing text/vector data. Log safe identifiers and shapes instead; do not emit raw exception/request bodies if they can contain source content.

## Edge Cases

- README is outside the configured handbook root; only Markdown files beneath the root are ingested.
- A single unreadable or unparsable file fails the whole snapshot; an empty but valid document is recorded in the run-document mapping with zero chunks.
- Removed/renamed files are omitted from future runs; historical document/run/chunk rows are retained.
- A failed run reuses its row with a new execution token on normal retry. Explicit stale recovery only marks the locked, still-running run failed and clears its token; it does not ingest. A later normal invocation claims it with a fresh token, fencing any previous worker.
- Parse/chunk failures happen before run creation and therefore have CLI logs, not persisted run status.
- `KnowledgeDocument` metadata may lag the filesystem; it reflects the last successful snapshot commit. Per-run historical hashes are authoritative.

## Risks & Unknowns

- The existing migration adds a non-null chunk run foreign key without backfill; it fails if the development database already contains chunks. The plan assumes it is empty.
- Snapshot identity is computed after parsing/chunking, so a repeat still spends local parsing/chunking work; only database writes and OpenAI calls are skipped.
- The handbook is captured per file, not as a filesystem-wide atomic snapshot; files added after discovery wait for the next run. Each individual stored hash nevertheless corresponds exactly to the bytes parsed for its chunks.
- Atomic publication intentionally repeats embeddings from a failed run on retry unless a completed run has the same text/model vector.
- Integration tests require a dedicated PostgreSQL database with pgvector and the user's CLI-generated migrations applied.

## Out of Scope

- Vector similarity search, retrieval evaluation, RAG, citations in answers, conversational features, and FastAPI endpoints.
- Automatic deletion of historical knowledge documents or chunks.
- Concurrent embedding requests, custom retry scheduling, staging/checkpoint tables, and automatic stale-run leases.
- Arbitrary embedding models or dimensions.

## Docs to Update

- N/A — no root `INDEX.md` exists; skipped index-based documentation discovery as instructed.
