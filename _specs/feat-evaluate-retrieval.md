# Retrieval Evaluation CLI

> 🌿 **Branch:** `feat/evaluate-retrieval` · 📅 **Date:** 2026-11-10

## Problem & Solution
**Problem:** Retrieval is implemented, but there is no repeatable way to compare chunking configurations. The dataset labels are deliberately incomplete, so treating unlisted results as irrelevant would make conventional relevance scores misleading.

**Solution:** Add a reusable evaluation function and module CLI that runs configurable retrieval experiments, reports incomplete-ground-truth evidence coverage and reviewable ranked chunks, and keeps human relevance and unsupported-query diagnostics distinct.

## Decisions

| Type | Decision | Choice | Why |
|---|---|---|---|
| Constraint | Retrieval | Reuse `app.ingestion.retrieval.retrieve_chunks()` and existing completed `IngestionRun` snapshots; do not ingest or add an endpoint. | Compare the implemented retrieval path and preserve run isolation. |
| Constraint | Dataset semantics | `known_relevant_sources` and `expected_evidence` are non-exhaustive. | An unlisted source/evidence is not proof of irrelevance. |
| Choice | Experiment grid | Default to the six rows in `docs/personal-documentation/retrieval.md`; allow Cartesian CLI overrides for strategies, token sizes, non-fixed overlap values and top-$k$ values. `fixed` always uses overlap 0. | Keep current comparisons reproducible while supporting future chunk-size studies. |
| Choice | Snapshot selection | Require exact strategy/token/overlap and completed status/model match. Auto-select only one exact match; allow repeated `--run-id STRATEGY:MAX:OVERLAP=UUID` overrides, still validated against the row. All selected runs must also represent the same source-only handbook snapshot. | Prevent silent comparisons against stale, mismatched, or different-source snapshots. |
| Choice | Shared source snapshot | Require every selected run and current local handbook to have the same source-only fingerprint before embedding any question. Compute from sorted relative paths and raw-content hashes; do not compare `snapshot_fingerprint`, which also includes strategy, chunk settings, model/dimensions, and candidate output. | Ensure strategies and evidence labels refer to the same source material while allowing strategy-specific chunk snapshots. |
| Choice | Evaluation architecture | Put reusable logic in `backend/app/evaluation/` and keep `backend/app/functions/evaluate_retrieval.py` as the thin CLI entrypoint. Start with `retrieval.py` and `metrics.py`; add `models.py` only if shared types warrant it. | Preserve modular boundaries without creating unnecessary files. |
| Choice | Retrieval efficiency | Request the maximum selected top-$k$ once per question/config and slice that ranked list for smaller cutoffs. Cache query embeddings only in-memory for one CLI invocation. | Avoid repeated ranking and embedding costs without persistent cache invalidation. |
| Choice | Embedding cache key | Key the per-invocation cache by embedding model and the exact question string supplied to `embed_texts()` after `retrieve_chunks()`'s intentional trim; do not casefold or collapse whitespace. | Avoid reusing a vector for a different actual embedding input. |
| Choice | Evidence match | Casefold and collapse whitespace; require each whole expected statement inside one retrieved chunk. Count each statement once per case, and retain every matching rank. | Deterministic and auditable; avoids merging unrelated chunks into a false match. |
| Choice | Metrics | Core eligible cases are exactly `answerable == true`, category is not `Prompt Injection and Instruction Handling`, and expected evidence is nonempty. EvidenceHit@K is 1 iff at least one expected statement is found; Recall@K is matched distinct statements / expected statements. Macro-average per-case values overall and by category over eligible cases only; empty denominators are `null` with count 0. Diagnostic categories report separate evidence metrics only for cases with expected evidence; otherwise metrics are `null`, never zero by implication. Label all as incomplete-ground-truth evidence coverage, not overall relevance or a strategy winner. | Makes the computable signal useful without overclaiming or ambiguous future denominators. |
| Choice | Human relevance | Include `relevance: null` for each returned chunk; Hit@K/MRR are unavailable until results are manually judged. | Evidence matching is not a substitute for human relevance. |
| Choice | Unsupported/injection cases | Report unanswerable and prompt-injection cases separately as retrieval diagnostics; do not treat any result as automatic failure or claim injection resistance. | Retrieval alone has no abstention threshold or LLM instruction handling. |
| Choice | Report | Write a detailed JSON report with per-case ranked chunks/content and aggregates; default to a UTC timestamped path under `backend/evaluation-reports`, support `--output`, require `--force` to overwrite, and write atomically. Print a concise console summary. | Enables review and reruns while preventing accidental overwrite. |
| Choice | Failures | Validate dataset/configurations before DB/API calls and preflight all required runs before embedding. Fail the complete run without writing a partial report. | Avoid misleading partial comparisons. |
| Choice | Integration | Provide `python -m app.functions.evaluate_retrieval` and README instructions; no taskipy alias. Require offline tests; PostgreSQL integration is optional. | Matches the existing module CLI pattern with a testable core. |
| Choice | Provenance | Record UTC timestamp, dataset SHA-256, run ID/fingerprint, strategy/configuration, embedding model and CLI parameters; omit Git commit metadata. | A copied report remains traceable to exact evaluation labels and indexed snapshots. |

## Architecture

```text
CLI args + dataset JSON
        │
        ▼
Validate schema, source paths/evidence, config product, output path
        │ invalid ──► safe error; no DB/API calls
        ▼
Resolve every exact completed run (or validate explicit run IDs)
        │ missing/ambiguous/mismatch ──► safe error; no embeddings/report
        ▼
For each unique run + case: embed once (invocation cache), retrieve max top_k once
        │
        ├──► slice ranks for requested top_k cutoffs
        ├──► match expected evidence within individual chunks
        └──► keep unanswerable/injection diagnostics separate
        ▼
Aggregate evidence coverage + serialize full per-case retrieval details
        │ failure ──► no report
        ▼
Atomic JSON report ──► concise CLI summary
```

## Code Shape

- Place reusable orchestration in `backend/app/evaluation/retrieval.py` and evidence metrics in `backend/app/evaluation/metrics.py`; keep CLI parsing/execution in `backend/app/functions/evaluate_retrieval.py`. Start with these two reusable modules; do not add `models.py` unless shared contracts prove it necessary.
- Dataset case fields remain `id`, `question`, `known_relevant_sources`, `expected_evidence`, `answerable`, `category`.
- Build unique experiment rows from selected strategies × max-token values × valid overlaps × top-$k$ values. Fixed strategy rows use overlap 0; other strategies use requested overlaps. Deduplicate rows before DB/API access.
- Report structure:
  - `metadata`: timestamp, dataset path/hash, CLI parameters, embedding model, shared source-only fingerprint.
  - `experiments[]`: one record per strategy/max-token/overlap/top-$k$ combination, with the shared source fingerprint, strategy-specific run ID and full snapshot fingerprint, configuration, case denominator/counts, and that cutoff's overall/category evidence metrics. Retrieval may still fetch maximum $K$ once internally.
  - Each experiment's `cases[]`: case ID/question/category/answerable, evidence statement matches and all matching ranks, per-case EvidenceHit@K/Recall@K where defined, listed-source diagnostic, and only the top-$K$ ranked chunks (`chunk_id`, rank, similarity, source, heading paths, `source_spans` as inclusive line pairs, content, `relevance: null`).
- Separate diagnostics for unanswerable and prompt-injection cases; no relevance metric until judgments exist.
- Use an invocation-scoped caching embedder for `retrieve_chunks()`; do not change the retrieval API unless necessary to inject cached vectors through its existing `embedder` parameter.

## Validation Rules

- CLI: strategies default to all three; max tokens default to 200; non-fixed overlap defaults to 40; top-$k$ defaults to 3 and 5. Values may be repeated to form a Cartesian product. Fixed always gets overlap 0. Reject nonpositive token sizes, overlap outside `[0, max_tokens)`, invalid fixed overlap combinations, top-$k$ outside retrieval's 1–100 limit, empty lists, and duplicate rows before DB/API calls.
- Dataset: require all six fields and correct JSON types; nonempty unique IDs/questions; recognized categories; answerable cases have nonempty source and evidence arrays; unanswerable cases have both arrays empty.
- Sources: require safe relative paths resolving beneath the handbook root and existing Markdown files; reject absolute paths and traversal.
- Evidence: before runtime calls, each expected statement must match its listed source after whitespace collapse and Unicode casefold. At evaluation time, each statement matches only if normalized text occurs in one of the top-$K$ result chunks. EvidenceHit@K is a binary per-case metric: at least one distinct expected statement matched. Evidence Recall@K is distinct matched expected statements divided by the case's expected statement count. Each statement contributes at most once to recall even if repeated across chunks; report all chunk ranks containing it.
- Runs: each unique strategy/token/overlap row requires one completed run with the supported embedding model. Explicit IDs must meet the same exact constraints. Missing or ambiguous automatic matches fail before embedding.
- Shared corpus: after resolving all runs, compute one source-only SHA-256 per run from canonical JSON containing objects `{path, source_hash}` sorted by repository-relative POSIX `path` (sort keys; compact UTF-8 serialization). Use `IngestionRunDocument.source_hash` and its related `KnowledgeDocument.file_path`; current dataset source labels are handbook-root-relative, so resolve them under the handbook root and convert to repository-relative paths for hashing. Compute local source hashes from raw file bytes using those same repository-relative paths. Require all selected runs and the current local handbook to match. The existing `IngestionRun.snapshot_fingerprint` is not source-only: `pipeline.snapshot_fingerprint()` also hashes strategy, token/overlap settings, embedding model/dimensions, and candidate content/metadata. Reject a mismatch before question embeddings.
- Output: refuse an existing destination unless `--force`; write to a sibling temporary file and atomically replace the destination only after successful serialization.

## Implementation Plan

### Phase 1: Evaluation model, validation, and metrics
| File | What changes |
|---|---|
| `backend/app/evaluation/retrieval.py` | Add dataset loading/validation, configurable experiment expansion, run preflight/shared-source validation, retrieval coordination and report assembly. |
| `backend/app/evaluation/metrics.py` | Add evidence normalization/matching and metric aggregation. |
| `backend/app/functions/evaluate_retrieval.py` | Add thin CLI argument parsing and `main()` wrapper. |
| `backend/tests/evaluation/test_retrieval.py` | Add offline tests for validation, Cartesian expansion/deduplication, matching boundaries, evidence metrics and category aggregates. |

- [ ] Define typed internal case/config/result structures and deterministic evidence-only metric functions.
- [ ] Confirm unanswerable and prompt-injection cases cannot enter primary evidence denominators.

### Phase 2: Run selection, retrieval, and CLI report
| File | What changes |
|---|---|
| `backend/app/evaluation/retrieval.py` | Add exact completed-run preflight, explicit run-ID mapping, shared source fingerprint check, exact-input/model invocation-scoped embedding cache, retrieval loop and report assembly. |
| `backend/app/functions/evaluate_retrieval.py` | Add safe runtime failure handling, atomic report output and module entry point. |
| `backend/tests/evaluation/test_retrieval.py` | Add fake session/embedder/retrieval tests, CLI validation/help/failure/output tests, run matching and cache behavior. |

- [ ] Resolve all unique configuration rows before retrieval; fail on missing, ambiguous or mismatched runs.
- [ ] Calculate source-only identities from `IngestionRunDocument` path/hash mappings; reject cross-run or local-handbook mismatches before calling the embedder.
- [ ] Retrieve each case at maximum selected top-$k$ once for each run; derive smaller cutoffs by slicing.
- [ ] Write no report on any run failure; do not persist a partial experiment grid.

### Phase 3: Documentation and operational verification
| File | What changes |
|---|---|
| `docs/personal-documentation/retrieval.md` | Clarify fixed-200-token defaults, configurable grid, evidence metric formulas/limitations, separate human relevance workflow, and record baseline results/limitations after experiments run. |
| `backend/README.md` | Document module invocation, defaults/overrides, database/provider prerequisites and report behavior. |
| `docs/roadmap.md` | Mark Phase 3 item 11 complete only after implementation, actual baseline experiment execution, and documentation of results/limitations. |

- [ ] Run offline tests and Ruff; verify `--help` works without DB/provider configuration.
- [ ] Run the six baseline experiments against actual completed runs sharing one source-only fingerprint; record result artifact/path and interpretation/limitations in `docs/personal-documentation/retrieval.md` (human Hit@K/MRR may remain pending).
- [ ] Optionally smoke-test against an operator-prepared PostgreSQL/pgvector database with exact matching completed runs.

## Acceptance Criteria

- `uv run python -m app.functions.evaluate_retrieval --help` works without database or embedding configuration.
- Default invocation builds exactly the six documented rows; custom repeated values form a validated Cartesian product, fixed overlap stays zero, and duplicate rows are removed.
- Dataset, source and evidence validation and configuration validation complete before DB/API calls.
- Every run is exact-config, completed and model-compatible; ambiguous/missing/mismatched runs fail before question embedding.
- All selected runs share the same source-only fingerprint calculated from sorted handbook-relative source paths and source hashes; the current local handbook used to validate evidence matches that same identity. Reject either mismatch before question embedding, and distinguish this shared source fingerprint from each strategy-specific full snapshot fingerprint in the report.
- Retrieval requests max top-$k$ once per question/config; smaller cutoffs use the same ordered results, and query vectors are reused only within the invocation.
- Query embedding cache key uses the exact question string passed to `EmbeddingService.embed_texts()` (after retrieval's intentional trimming) plus model; no evidence normalization is applied.
- Evidence matching is normalized whitespace + casefold, whole statement within one chunk; duplicate chunk matches count once in recall and all matching ranks are recorded.
- EvidenceHit@K and evidence Recall@K use only cases satisfying `answerable == true`, category != `Prompt Injection and Instruction Handling`, and nonempty expected evidence; each denominator is reported explicitly, and empty groups yield `null` with count 0. Diagnostic categories calculate evidence metrics only when evidence exists. All scores are labeled incomplete-ground-truth coverage, not overall relevance or a winner.
- Unanswerable and prompt-injection cases are separate diagnostics; manual Hit@K/MRR remain unavailable and each result has a pending `relevance: null` field.
- JSON includes one experiment record per strategy/token/overlap/top-$k$ row and per-case top-$K$ chunks/content, score/source/heading/source spans as inclusive line pairs/chunk ID, matched evidence and all matching ranks, source diagnostics, run IDs/full and shared-source fingerprints, dataset hash, model, configs, timestamp and exact metric denominators.
- Default timestamped output, custom path, overwrite guard and atomic write work; failures produce a safe error and no partial report.
- Offline tests cover metric boundaries, validation, run resolution, shared-source fingerprint match/mismatch, exact-input cache behavior, CLI behavior, serialization and safe errors; no live provider call is required.
- Phase 3 item 11 is complete only after the runner is validated, the six baseline experiments have run against actual compatible snapshots, and results/limitations are documented; CLI test success alone is insufficient.

## Testing

- Unit-test normalization (whitespace, casefold, punctuation preservation), within-one-chunk matching, split-across-chunks non-match, duplicate evidence in overlapping chunks, zero/partial/full recall, EvidenceHit@K, macro versus category denominators, and empty denominator behavior.
- Include hand-calculated metric fixtures: a case with no evidence matches (EvidenceHit@K = 0, Recall@K = 0), a partially matched case, a fully matched case, and an empty-evidence diagnostic case (both metrics `null`). Verify macro averages include only eligible cases and report the exact eligible-case count.
- Assert exact evidence formulas: EvidenceHit@K is 1 iff at least one distinct expected statement is found; Recall@K is distinct matched expected statements / expected statements; repeated matches count once but all ranks are retained. Empty evidence produces `null`, never division by zero.
- Test dataset schema/types, duplicate IDs/questions, recognized categories, answerable/unanswerable array rules, source traversal/absolute/missing paths, and evidence-source mismatches.
- Test strategy/token/overlap/top-$k$ Cartesian expansion, defaults, fixed overlap, invalid bounds and duplicate removal before any DB/API call.
- Fake database runs to test exact configuration/model/status filtering, explicit run validation, missing/ambiguous selection and preflight of all rows before embedder calls.
- Test source-only fingerprint determinism independent of strategy/token/overlap/model, and reject runs whose sorted path/source-hash mapping differs before any embedder call. Confirm the full `snapshot_fingerprint` is strategy/config-dependent and must not be used for cross-strategy equality.
- Verify local handbook files used for evidence validation have the same canonical source-only fingerprint as selected runs; stale local content fails preflight.
- Fake retrieval/embedder to assert one max-top-$k$ call per case/run, correct slicing, invocation-only embedding reuse, per-case records and distinct diagnostic grouping.
- Test embedding cache exactness: strings that differ only by case are distinct keys; strings that retrieval trims to the same exact embedder input may share a cached vector; model changes invalidate the key.
- Test atomic JSON output, existing-path refusal/`--force`, failures leaving no partial report, safe stderr, and subprocess `--help` without runtime setup.
- Optional PostgreSQL test verifies run selection query against the migrated schema and one representative retrieval/report round trip; never use the application DB as a test database.

## Logging

Log configuration and stable identifiers, not raw questions, chunk text, evidence text, vectors, credentials or sensitive SQL parameters. DEBUG entry/exit records include safe case IDs, config, run IDs, metric outputs and durations. No LLM is called in this phase.

| Event | Level | Fields | Example |
|---|---|---|---|
| Evaluation started | `info` | `invocation_id`, `dataset_sha256`, `case_count`, `configurations`, `top_ks` | `{invocation_id: "8c41…", dataset_sha256: "a93f…", case_count: 24, configurations: [{strategy: "fixed", max_tokens: 200, overlap_tokens: 0}], top_ks: [3, 5]}` |
| Dataset/config validation failed | `warning` | `invocation_id`, safe `reason_code`, `case_id`/field if applicable | `{invocation_id: "8c41…", reason_code: "evidence_not_in_listed_source", case_id: "TEST-007", field: "expected_evidence[1]"}` |
| Run selected | `info` | `invocation_id`, `strategy`, `max_tokens`, `overlap_tokens`, `run_id`, `snapshot_fingerprint`, `source_fingerprint`, `embedding_model` | `{invocation_id: "8c41…", strategy: "heading_aware", max_tokens: 200, overlap_tokens: 40, run_id: "8b7d…", snapshot_fingerprint: "2b7e…", source_fingerprint: "7d91…", embedding_model: "text-embedding-3-small"}` |
| Retrieval case entry/exit | `debug` | `invocation_id`, `case_id`, `run_id`, `max_top_k`, result ranks/IDs/scores, `duration_ms` | `{invocation_id: "8c41…", case_id: "TEST-001", run_id: "8b7d…", max_top_k: 5, results: [{chunk_id: "a102…", rank: 1, similarity_score: 0.842}], duration_ms: 93.1}` |
| Experiment completed | `info` | `invocation_id`, config, run ID, evidence hit/recall aggregates and category values | `{invocation_id: "8c41…", strategy: "fixed_overlap", max_tokens: 200, overlap_tokens: 40, run_id: "8b7d…", evidence_hit_at_3: 0.73, macro_evidence_recall_at_3: 0.61, judged_mrr: null}` |
| Evaluation failed | `error` | `invocation_id`, config/case ID if known, safe `reason_code` | `{invocation_id: "8c41…", strategy: "fixed", max_tokens: 200, overlap_tokens: 0, reason_code: "database_error"}` |
| Report written | `info` | `invocation_id`, output path, dataset hash, experiment count | `{invocation_id: "8c41…", output: "evaluation-reports/retrieval-20261110T120000Z.json", dataset_sha256: "a93f…", experiment_count: 6}` |

## Edge Cases

- `fixed` is paired only with overlap 0 even when other strategies use multiple overlap values.
- All selected runs must have identical source paths and source hashes, and must match local handbook files, even though their full run fingerprints differ by chunking strategy/configuration.
- Multiple top-$k$ values share one maximum-$k$ ranking; absent ranks at a smaller cutoff are not synthesized.
- An evidence statement split between chunks does not match; evidence appearing in multiple chunks contributes once to recall.
- A category with zero metric-eligible cases has null aggregate metrics and an explicit zero denominator, not a fabricated zero score. An answerable diagnostic case with evidence may have per-case evidence diagnostics but does not enter the core denominator if it is prompt-injection category.
- Unanswerable cases can retrieve chunks; show them as diagnostics, not false-positive failures without an abstention policy.
- Prompt-injection cases assess retrieval content only; they do not prove instruction resistance.
- A timestamp collision or existing custom path never silently overwrites without `--force`.
- A retrieval/serialization error after some experiments have run still yields no final report.

## Risks & Unknowns

- This phase does not produce fully human-judged Hit@K/MRR; evidence coverage can rank configurations poorly when labels omit useful evidence. Manual review is required before claiming a best strategy.
- Exact string evidence validation may reject curated paraphrases; update dataset evidence to a handbook-verbatim statement rather than weakening matching silently.
- Cartesian grids grow multiplicatively and increase DB/API costs; report expanded row count before calls and validate against retrieval's `top_k <= 100` limit.
- Full chunk content makes reports larger and carries handbook text outside the database; users selected committing reports by default, so review artifact handling before sharing.
- The current `retrieve_chunks()` resolves runs by strategy by default; evaluator must query/validate configuration itself and pass the explicit run ID.
- `pipeline.snapshot_fingerprint()` intentionally changes across chunking configs and models, so it cannot establish that selected strategies indexed identical source files. The evaluator needs a canonical source-only identity based on `IngestionRunDocument` mappings.
- `retrieve_chunks()` strips leading/trailing whitespace before calling `embed_texts()`. Cache keys must match that exact effective API input and model, while preserving case and internal whitespace.

## Out of Scope

- Ingestion or automatic creation of missing experiment snapshots.
- LLM answer generation, groundedness/citation evaluation, prompt-injection resistance, or automatic abstention thresholds.
- Automatic human relevance labeling or a final strategy winner; manual judgment workflow beyond pending report fields.
- Persistent embedding cache, metric database, web UI, taskipy alias, or Git commit metadata.
- Changing the current dataset size/category distribution; validation permits future additions.

## Docs to Update

- No root `INDEX.md` exists; index-based documentation discovery is skipped.
- `docs/personal-documentation/retrieval.md` — finalized runner/metric limitations and configurable experiment defaults; append actual baseline results, interpretation, and limitations after running the six default rows.
- `backend/README.md` — CLI usage and prerequisites.
- `docs/roadmap.md` — mark Phase 3 item 11 complete only after implementation, actual baseline experiment execution against shared-source snapshots, and documentation of results/limitations.
