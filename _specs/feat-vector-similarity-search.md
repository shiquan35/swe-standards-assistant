# Exact Vector Similarity Retrieval

> 🌿 **Branch:** `feat/vector-similarity-search` · 📅 **Date:** 2026-11-05

## Problem & Solution
**Problem:** Ingestion persists strategy-specific chunks and 1,536-dimensional embeddings, but the backend has no query path to retrieve relevant chunks. The semantic and multi-section test questions therefore cannot use the knowledge base.

**Solution:** Add a Python retrieval function that embeds a question and returns the top-k chunks from one completed run using exact cosine similarity, with document and chunk provenance for later evaluation and RAG use.

## Decisions

| Type | Decision | Choice | Why |
|---|---|---|---|
| Constraint | Stored vector contract | `text-embedding-3-small`, 1,536 dimensions | Matches the existing embedding service and `Vector(1536)` schema. |
| Constraint | Chunk strategies | `fixed`, `fixed_overlap`, `heading_aware` | Existing `ChunkStrategy` literal and ingestion-run constraint. |
| Constraint | Persistence | Reuse existing schema; no migration or vector index | The embedding column and run/document relationships already exist; exact NN is required. |
| Choice | Interface | Python function only; caller supplies `Session`; injectable embedder | Keeps Phase 3 retrieval reusable by future RAG and evaluation without adding HTTP API now. |
| Choice | Run scope | Required strategy; newest completed run for it by `created_at DESC, id ASC`; optional explicit run ID overrides selection only after matching strategy/status/model validation | Keeps each evaluation strategy and ingestion snapshot isolated and deterministic. Never combine or silently fall back across runs. |
| Choice | Ranking | Raw cosine similarity descending; UUID ascending for ties; rank starts at 1 | Similarity score remains interpretable and ordering is deterministic. |
| Choice | Result contract | Frozen typed result with 11 fields: chunk/document IDs, content, score, rank, strategy, token count, all heading paths, source-span pairs, file path, title | Carries retrieval evidence and full available provenance without losing multi-path metadata. |
| Choice | Validation/failure | Strict arguments and query-vector validation; `ValueError` for invalid input; content-free `RetrievalError` for run/data/DB failures; propagate sanitized `EmbeddingError` | Fail safely and preserve existing embedding failure codes. |
| Choice | Metadata validation | Validate required metadata only for selected top-k rows; any malformed selected row fails the call | Avoid rejecting results because of irrelevant lower-ranked rows while keeping returned results trustworthy. |
| Choice | Query privacy | Strip query whitespace before embedding; never log raw question, vector, chunk text, or metadata content | Avoid sensitive-content leakage and normalize equivalent questions. |

## Architecture

```text
Caller (Session, question, strategy, top_k, optional run_id, optional embedder)
        │
        ▼
1. Validate question, strategy, top_k, run-ID type
        │
        ▼
2. Resolve/validate one completed run (created_at DESC, id ASC)
        │  none for strategy ──► [] (no embedding API call)
        │  invalid explicit/wrong-model run ──► RetrievalError
        ▼
3. Embed stripped question with text-embedding-3-small
        │
        ▼
4. Validate 1536 finite numeric values and non-zero magnitude
        │  malformed output ──► sanitized EmbeddingError
        ▼
5. Exact cosine search, filtering selected run + strategy + non-null vectors,
   ordering by distance then chunk UUID; apply top_k after filters/ranking
        │
        ▼
6. Validate metadata for selected top-k rows; map document provenance
        │
        ▼
list[RetrievalResult], ranks 1..k (never commit, roll back, or close Session)
```

## Code Shape

- Add a retrieval module under `backend/app/ingestion/` (suggested `retrieval.py`) and a frozen `RetrievalResult` dataclass.
- Public operation: `retrieve_chunks(*, session: Session, question: str, strategy: ChunkStrategy, top_k: int = 5, ingestion_run_id: UUID | None = None, embedder: EmbeddingService | None = None) -> list[RetrievalResult]`.
- Result fields:
  - `chunk_id: UUID`, `document_id: UUID`, `content: str`
  - `similarity_score: float`, `rank: int`, `strategy: ChunkStrategy`
  - `tokens: int`, `heading_paths: list[list[str]]`, `source_spans: list[list[int]]`
  - `file_path: str`, `title: str`
- Use SQLModel/SQLAlchemy pgvector cosine distance ordering; convert distance to raw cosine similarity. Ensure exact search and deterministic tie-break ordering. Join selected chunks to their document and run records.

## Validation Rules

- `question`: must be a string with non-whitespace content; strip before embedding.
- `strategy`: strict one of `fixed`, `fixed_overlap`, `heading_aware`.
- `top_k`: integer 1–100 inclusive; reject booleans and non-integers. Default 5.
- `ingestion_run_id`: UUID or `None`; if supplied, run must exist, be completed, match strategy and `text-embedding-3-small`; otherwise raise `RetrievalError("run_not_searchable")`.
- Default run: select newest completed run for the strategy, ordered `created_at DESC, id ASC`, then validate its model. No completed run returns `[]`; a wrong-model newest run raises `RetrievalError("run_not_searchable")`. Never skip it to fall back to an older compatible run.
- Resolve and validate the run before calling the embedder. If no completed run exists for the selected strategy, return `[]` without an embedding API call.
- Query embedding: exactly one vector of 1,536 finite numeric values and non-zero magnitude; reject booleans, wrong cardinality/dimensions, non-numeric/non-finite values, and zero vectors before database search. Invalid embedder output raises sanitized `EmbeddingError("invalid_query_vector")`; provider failures propagate their existing sanitized `EmbeddingError`.
- Search only non-null embeddings in the selected run; exact cosine ranking, no threshold.
- Apply strategy/run filters before cosine ranking and `top_k`; never limit candidates before filtering.
- Validate metadata only for top-k selected rows: `token_count` is non-bool int ≥ 0; `heading_paths` is `list[list[str]]`; `source_spans` is a list of mappings with positive integer `start_line`/`end_line` and `start_line <= end_line`. Convert spans to `[start_line, end_line]` pairs. Invalid selected metadata raises `RetrievalError("invalid_chunk_metadata")`; database failures raise `RetrievalError("database_error")`.
- No matches or no usable chunks returns `[]`.
- Borrowed session is read-only from retrieval’s perspective: never commit, roll back, or close it.

## Implementation Plan

### Phase 1: Retrieval contract and query embedding
| File | What changes |
|---|---|
| `backend/app/ingestion/retrieval.py` | Add retrieval errors/result type, strict input/vector validation, run resolution, exact cosine query, metadata conversion and safe structured logs |
| `backend/tests/ingestion/test_retrieval.py` | Add input, embedding, run-selection, ranking, metadata and session-ownership tests using deterministic fakes |
| `backend/app/models/knowledge.py` and existing Alembic migrations | Verify the existing `KnowledgeChunk.ingestion_run_id` foreign key and document/run relationships support filtering and source joins; change schema only if verification disproves the no-migration assumption |

- [ ] Verify `IngestionRun` status/strategy/model/timestamp fields and `KnowledgeChunk` run/document foreign keys in SQLModel and migrated PostgreSQL schema; confirm run filtering and document joins require no migration.
- [ ] Implement input validation, then run resolution/validation before embedding; return `[]` without embedding when no default completed run exists.
- [ ] Validate query embedding (including non-zero magnitude) before vector search; malformed embedding output raises `EmbeddingError("invalid_query_vector")`.
- [ ] Execute exact cosine search after strategy/run/non-null-vector filters, apply `top_k` after filtering and ordering, and map validated selected rows to typed results.

### Phase 2: PostgreSQL verification and retrieval cases
| File | What changes |
|---|---|
| `backend/tests/ingestion/test_retrieval_postgres.py` | Add guarded PostgreSQL/pgvector tests for operator semantics, exact ordering, strategy/run filtering, null-vector exclusion and joins |
| `backend/tests/ingestion/test_retrieval.py` | Add deterministic fixtures for representative semantic and multi-section handbook queries |

- [ ] Verify raw cosine score conversion, stable UUID tie ordering, result provenance and metadata validation against PostgreSQL.
- [ ] Exercise representative TC-006–TC-015 questions with fixtures/deterministic embeddings; no live provider calls.

## Acceptance Criteria

- A caller can retrieve typed results through a Python function using its existing session; no endpoint or answer-generation call is added.
- The question is embedded using `text-embedding-3-small`; invalid questions and malformed vectors fail before database search.
- Run resolution occurs before embedding; no available default run returns `[]` without invoking the embedder. Invalid explicit runs also fail before embedding.
- Query vectors with zero magnitude are rejected with sanitized `EmbeddingError("invalid_query_vector")`, as are malformed dimensions, non-numeric values, booleans and non-finite values.
- Retrieval searches exactly one completed run for the required strategy, selected by `created_at DESC, id ASC` or explicitly by run ID; validate the selected run's model and never combine or fall back across runs.
- Search filters by strategy, selected run, and non-null embeddings before exact cosine ranking and applying `top_k`; results are sorted descending with stable tie order and contiguous 1-based ranks.
- Empty/unavailable default corpus or no matching embedded chunks returns `[]`; explicit invalid run IDs raise `RetrievalError("run_not_searchable")`.
- Returned values include all 11 agreed fields; heading paths are not discarded and source spans use inclusive `[start_line, end_line]` pairs.
- Required metadata is validated only for selected top-k rows; malformed selected metadata raises a safe retrieval error.
- Retrieval does not commit, roll back, or close the caller’s session; logs contain no question, vector, chunk text or source metadata content.
- Unit and PostgreSQL tests verify input validation, run selection, model/strategy isolation, exact score/order, result mapping and empty-result behavior without live embedding API calls.

## Testing

- Unit tests: empty/whitespace/non-string questions; invalid strategy; `top_k` boundaries and bool rejection; embedder error propagation; vector cardinality, dimensions, numeric types and finite values; assert DB search is not reached for invalid vectors.
- Use fake sessions/embedder for deterministic run-selection and result contract tests; assert newest ordering, explicit run override validation, run resolution before embedding, no-run/no-match behavior, selected-run isolation, stable ties, ranks, provenance mapping and no session commit/rollback/close.
- Assert zero-magnitude generated vectors raise `EmbeddingError("invalid_query_vector")` and never reach the database search.
- Test malformed metadata only in selected top-k rows; malformed rows ranked below top-k must not fail the request.
- PostgreSQL integration: run against a dedicated migrated `TEST_DATABASE_URL` with pgvector; verify existing schema relationships/foreign keys support filtering by `ingestion_run_id` and joining source documents without a migration; assert SQL cosine operator/score semantics, exact nearest-neighbour ordering, null embedding exclusion, strategy/run filters and joins. Follow existing `TEST_DATABASE_ALLOW_DESTRUCTIVE=1` safeguards; never use the app DB or SQLite as a vector substitute.
- Repeat the same query against the same run and assert identical result ordering; verify `top_k` is applied after strategy/run filtering so unrelated higher-scoring rows cannot consume result slots.
- Include representative TC-006–TC-015 questions with deterministic vectors/fixtures; defer judged retrieval-quality evaluation to roadmap item 11.

## Logging

Never log raw questions, embeddings, chunk content, headings, metadata payloads, or document paths. Use safe IDs and values for observability. Entry/exit logs capture function inputs/outputs structurally but substitute the query with its character length and never include text/vector values.

| Event | Level | Fields | Example |
|---|---|---|---|
| Retrieval entry | `debug` | `strategy`, `top_k`, `ingestion_run_id`, `question_chars`, `embedding_model` | `{function: "retrieve_chunks", strategy: "heading_aware", top_k: 5, ingestion_run_id: null, question_chars: 48, embedding_model: "text-embedding-3-small"}` |
| Run selected | `debug` | `strategy`, `run_id`, `created_at`, `selection` | `{strategy: "fixed_overlap", run_id: "8b7d…", created_at: "2026-11-04T10:20:00Z", selection: "latest_completed"}` |
| Vector query | `debug` | query/operator name, `run_id`, `strategy`, `top_k`, `embedding_dimensions`, `duration_ms` | `{operation: "exact_cosine_search", operator: "cosine_distance", run_id: "8b7d…", strategy: "heading_aware", top_k: 5, embedding_dimensions: 1536, duration_ms: 12.4}` |
| Search completed | `debug` | `run_id`, `strategy`, `top_k`, result IDs/ranks/scores, `duration_ms` | `{run_id: "8b7d…", strategy: "fixed_overlap", top_k: 5, results: [{chunk_id: "a102…", rank: 1, similarity_score: 0.842}], duration_ms: 12.4}` |
| Retrieval returned | `debug` | `run_id`, `result_count`, safe result IDs/ranks, `duration_ms` | `{function: "retrieve_chunks", run_id: "8b7d…", result_count: 2, results: [{chunk_id: "a102…", rank: 1}, {chunk_id: "4c11…", rank: 2}], duration_ms: 93.1}` |
| Validation/run/data failure | `warning` or `error` | safe `reason_code`, `strategy`, `run_id` if available | `{function: "retrieve_chunks", reason_code: "invalid_chunk_metadata", strategy: "fixed", ingestion_run_id: "8b7d…"}` |
| Embedding failure | `error` | `model`, safe `reason_code`, `duration_ms` | `{model: "text-embedding-3-small", reason_code: "rate_limited", duration_ms: 301.0}` |
| Database failure | `error` | operation, `run_id`, `strategy`, safe error class/reason, duration | `{operation: "vector_search", run_id: "8b7d…", strategy: "heading_aware", reason_code: "database_error", duration_ms: 12.4}` |

## Edge Cases

- A strategy has no completed run: return `[]`; a specific supplied run that is absent/ineligible raises `run_not_searchable`.
- Invalid or unavailable runs are resolved before query embedding, preventing unnecessary provider calls.
- A chosen run has no non-null embeddings: return `[]`, without falling back to an older run.
- A zero-magnitude query vector is invalid because cosine similarity is undefined for it; reject before SQL execution.
- Identical similarity scores: order by chunk UUID ascending before assigning ranks.
- A selected top-k chunk has malformed/missing metadata: fail with a content-free data error; malformed lower-ranked rows are irrelevant.
- Query text with leading/trailing whitespace is stripped; whitespace-only text is rejected.
- Caller session may already have a transaction; retrieval does not alter its lifecycle or commit state.

## Risks & Unknowns

- Cosine-distance operator and score conversion must be verified against PostgreSQL/pgvector, not inferred from SQLite behavior.
- Exact nearest-neighbour may become slower as the corpus grows; approximate indexes/performance tuning are intentionally deferred until measurement.
- Existing chunk metadata is JSONB; validation must handle unexpected historical data safely without logging values.

## Out of Scope

- HTTP/API endpoint, LLM/RAG generation, conversation/query rewriting, similarity threshold, ANN index, pagination, user/tenant filtering, citations in generated answers, and retrieval-quality optimization (roadmap items 11–12).
- Schema changes, migrations, new embedding model support, or per-user corpus authorization.

## Docs to Update

No root `INDEX.md` exists, so index-based documentation discovery is skipped. `docs/roadmap.md` needs item 10 marked complete after implementation; no other documentation change is currently required.
