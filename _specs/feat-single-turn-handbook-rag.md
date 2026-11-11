# Single-Turn Handbook RAG with Citations

> 🌿 **Branch:** `feat/single-turn-handbook-rag` · 📅 **Date:** 2026-11-11

## Problem & Solution
**Problem:** Handbook retrieval returns ranked excerpts but does not generate an answer, attribute individual claims to sources, or distinguish unsupported questions from operational failures.

**Solution:** Add a stateless, evidence-only Python RAG function and CLI. It retrieves up to five heading-aware chunks, makes at most one structured OpenAI generation request when evidence exists, and returns cited claims, clarification/partial outcomes, or an abstention.

## Decisions

| Type | Decision | Choice | Why |
|---|---|---|---|
| Constraint | Retrieval contract | Reuse exact cosine `retrieve_chunks()` and existing embedding model | Keep Phase 4 on the completed retrieval foundation. |
| Constraint | Runtime boundary | Single question; no history, persistence, or HTTP endpoint | Phase 4 is stateless and CLI-invoked. |
| Constraint | Logging/privacy | Log operational metadata only; never question, prompt, context, completion, or answer text | Prevent sensitive interaction content entering logs, including DEBUG. |
| Choice | Retrieval | `heading_aware`, `top_k=5`; newest completed run; no fallback if its embedding model mismatches | Deterministic use of current retrieval behavior. |
| Choice | Generation | OpenAI Responses API Structured Outputs; `OPENAI_CHAT_MODEL=gpt-6-luna`; one generation request maximum, automatic retries disabled | One schema-constrained generation step per question; embedding request remains separate. |
| Choice | Context limits | `RAG_MAX_INPUT_TOKENS=32000`; `RAG_MAX_OUTPUT_TOKENS=4096`; `RAG_TOKEN_SAFETY_MARGIN=.20`; `RAG_MODEL_CONTEXT_WINDOW=1050000`; estimate the complete serialized request/schema plus 256 framing tokens, then multiply by 1.2 | Conservative local budgeting, not a guarantee of provider limits or verified model capacity. |
| User override | Tokenizer compatibility | Try `tiktoken.encoding_for_model()`; unknown model mapping falls back to `o200k_base`, explicitly marked as unverified estimation | User-directed fallback replaces strict unknown-tokenizer failure. Never present the fallback as verified model mapping. |
| Choice | Evidence and citations | Evidence-only claims; model returns cited chunk IDs; application constructs provenance and checks references | Keep source metadata application-owned; no second model judge. Citation support is model-proposed, not independently verified. |
| Choice | Outcomes | `answered`, `partial`, `clarification_needed`, `abstained`; ambiguity takes precedence over partial | Explicitly distinguish answer content states. |
| Choice | CLI | Required positional question; human output by default, `--json` for JSON; mode-matched sanitized errors to stderr | Support people and scripts without exposing provider details. |

## Architecture

```text
CLI(question, --json?)
        │ creates Session; calls answer_question()
        ▼
RAG service ──► resolve newest completed heading_aware run
        │                    │ none/mismatched model → typed operational error
        │                    ▼
        ├────► retrieve_chunks(run_id, top_k=5) ──► question embedding + cosine search
        │                    │
        │                    ├── zero chunks ──► abstained (no generation request)
        │                    ▼
        │          fit ranked chunk prefix to input budget
        │                    │
        │                    ▼
        ├────► OpenAI Responses structured output (≤1 request)
        │                    │ claims cite retrieved chunk IDs
        │                    ▼
        ├────► validate response and IDs; build citation provenance; attach run ID
        ▼
Typed RagResponse ──► human renderer or JSON stdout
```

## Code Shape

- `backend/app/rag/models.py`: Pydantic `RagResponse`, `Claim`, and `Citation`; statuses are `answered | partial | clarification_needed | abstained`. All schema fields are required; nullable values use `null`, absent heading paths/source spans use empty lists. `Claim` has atomic `text` and one-or-more `citation_ids`. `Citation` has chunk ID, nullable title/source path, heading paths, and source spans. Final response also has ingestion run ID, nullable clarifying question/reason, and unanswered parts. No free-form `answer_text`. Enforce status-specific cross-field invariants in Pydantic after parsing.
- The model-output schema excludes application-owned citation metadata and run ID. Model returns status, claims with retrieved chunk IDs, clarifying question, reason, and unanswered parts. The app validates IDs, builds deduplicated citation records, and attaches the selected run ID.
- `backend/app/rag/errors.py`: `RagError` with allowlisted stable reason codes and sanitized messages; preserve provider/database exceptions only as internal causes.
- `backend/app/rag/service.py`: `answer_question(*, session: Session, question: str, openai_client: OpenAI | None = None) -> RagResponse`. Caller owns session. Validate nonempty question, resolve run before retrieval, enforce budget, generate once, validate and assemble response. Derive a request-scoped client with `openai_client.with_options(max_retries=0)` so injected clients cannot trigger automatic generation retries.
- A reusable retrieval resolver returns the newest completed run for the strategy; no run raises a safe missing-snapshot error. A model mismatch on that newest run raises; do not fall back to older runs. Pass its ID explicitly to `retrieve_chunks()` to distinguish empty retrieval from missing snapshot.
- `backend/app/functions/answer_handbook.py`: CLI lazily imports runtime settings/DB after argparse, creates the app session, and lets the service own its default client. Accepts a positional question and `--json`; renders human claims with inline numbered references and source title/path/headings/spans, reason, unanswered parts, and clarifying question. Returns 0 for every successful content status, 1 for operational failures, 2 for invalid arguments; safe mode-matched errors go only to stderr.

## Validation Rules

- Reject empty/whitespace question before database, embedding, or model calls; normalize by trimming outer whitespace.
- Always retrieve `heading_aware` with `top_k=5`.
- Model/account availability and live Responses/Structured Outputs compatibility remain unverified until an explicit operator-owned live smoke test before rollout; no account-availability gate blocks implementation or offline tests. Use the installed SDK schema adapter. By user override, try `tiktoken.encoding_for_model()` and fall back on unknown model mapping to `o200k_base`, explicitly unverified estimation; record the encoding and fallback metadata. Failure to load any usable encoding remains a safe configuration error.
- Build the exact logical request payload passed to Responses, then budget all serialized inputs: model/instructions, escaped question/evidence JSON, chunk IDs, titles/paths/headings/spans, delimiters, metadata included in prompt, structured-output schema/format and other request fields. Compute `estimated_input_tokens = ceil((serialized_tokens + 256) * (1 + RAG_TOKEN_SAFETY_MARGIN))`, multiplying by 1.2 at the default .20 margin. Require the estimate to fit `RAG_MAX_INPUT_TOKENS` and `estimated_input_tokens + RAG_MAX_OUTPUT_TOKENS <= RAG_MODEL_CONTEXT_WINDOW` (default 1050000, operator-configured and unverified). Include a contiguous ranked prefix only. Stop at first chunk that will not fit; if prompt/question/schema alone exhaust the budget or the first chunk cannot fit, raise `context_budget_exceeded` without generation. Never truncate or skip chunks. Estimates are not guaranteed limits; provider context-limit rejection is a typed operational `provider_context_limit` error. Compare actual input/output usage with the estimate in metadata-only logs when usage is available.
- An answer claim must be atomic, cite at least one ID from a chunk actually included in the generation request, and contain no duplicate citation IDs. The final citation list must equal exactly the deduplicated IDs referenced by claims; reject retrieved-but-excluded chunks, unreferenced citation records, invalid IDs, or a claim without citations. Include nullable title/path and heading/span arrays; fail with `invalid_citation_source` if both title and path are blank.
- Enforce these cross-field invariants in `RagResponse` after parsing (all fields exist; nullable fields use null):

| Status | Claims | Clarifying question | Unanswered parts | Reason |
|---|---|---|---|---|
| `answered` | Nonempty; every claim cited | Null | Empty | Null |
| `partial` | Nonempty; every claim cited | Null | Nonempty | Null |
| `clarification_needed` | Optional; any claims must be cited | Nonempty | Optional | Null |
| `abstained` | Empty | Null | Empty | Required, meaningful “I don't know” explanation |

- Citation IDs in claims are unique per claim; the final citation list is exactly the deduplicated union of IDs referenced by claims. Explanatory fields must not introduce uncited factual claims.
- Semantics: `answered` means all requested claims are supported; `partial` means a clear request has supported claims and explicit unanswered parts; `clarification_needed` means ambiguity blocks interpretation, may include independently supported cited claims and one concise question; `abstained` means no requested claim is supportable, with concise “I don't know based on the available handbook evidence” reason.
- Missing snapshot, run-model mismatch, missing API key, embedding/database/provider failure, model refusal, invalid model output/citation, or context overflow is a typed operational error, never an abstention. Successful retrieval with zero chunks is an abstention and makes no generation request.

## Implementation Plan

### Phase 1: Contracts, configuration, and snapshot resolution
| File | What changes |
|---|---|
| `backend/app/core/env.py` | Add generation model and RAG input/output token settings with documented defaults. |
| `backend/env.example` | Document non-secret setting names/defaults. |
| `backend/app/ingestion/retrieval.py` | Add latest-completed-run resolver preserving current newest-run/no-fallback semantics. |
| `backend/app/rag/models.py` | Define typed response and model-output schema models. |
| `backend/app/rag/errors.py` | Define safe RAG error codes. |
| `backend/tests/ingestion/test_retrieval.py` | Cover resolver: missing, latest run, mismatch/no fallback. |
| `backend/tests/rag/test_models.py` | Test response serialization and semantic validation. |

- [ ] Define stable response/error contracts and defaults; inspect installed SDK Responses parsing and schema support offline. Keep `gpt-6-luna` model/account and live schema compatibility explicitly unverified, not an implementation gate. Implement the user-overridden unknown-model `o200k_base` estimation fallback and expose fallback metadata; do not silently substitute an API or claim verified tokenizer compatibility.
- [ ] Tell the user to set `OPENAI_CHAT_MODEL=gpt-6-luna` themselves in local ignored settings if a previous value overrides the default. Do not read, edit, or commit `.env` or credentials during implementation/offline validation.

### Phase 2: RAG orchestration and deterministic tests
| File | What changes |
|---|---|
| `backend/app/rag/service.py` | Orchestrate run resolution, retrieval, model-aware context budget, one Responses call, citation validation, and response assembly. |
| `backend/tests/rag/test_service.py` | Cover answer, partial, clarification, abstention, budgets, citation validation, injection boundary, and safe failures with fakes. |

- [ ] Ensure empty retrieval skips generation; derive the effective request-scoped client with `openai_client.with_options(max_retries=0)`, including when the caller injects a client with retries enabled; embedding retries remain unchanged.
- [ ] Pass retrieved chunks as untrusted evidence; parameterize generation cases in `test_service.py` using existing retrieval examples plus ambiguous, partial, and injection-like scenarios; reject citations outside the included prompt chunks and validate exact referenced-source set.
- [ ] Cover complete serialized-input accounting (IDs/headings/delimiters/schema/framing256, then the .20 margin), prompt+question exhaustion, first-chunk overflow, estimated-input+output context-window bound, unknown-model `o200k_base` estimation fallback, encoding-load failure, missing API key, provider context-limit rejection/refusal/failure, incomplete output at max tokens, and invalid status combinations.

### Phase 3: CLI and operator documentation
| File | What changes |
|---|---|
| `backend/app/functions/answer_handbook.py` | Add positional-question CLI, human renderer, `--json`, and sanitized mode-matched errors. |
| `backend/tests/rag/test_answer_handbook.py` | Test argument validation, both output modes, exit codes, and stderr safety. |
| `backend/tests/rag/test_live.py` | Opt-in `RUN_LIVE_RAG_TEST=1` smoke using the app session and real OpenAI; default skipped. |
| `backend/README.md` | Document invocation, configuration, response/status semantics, snapshot prerequisites, and safe errors. |
| `backend/env.example` | Verify final generation and budget settings are documented. |

- [ ] Keep provider and database details out of CLI errors; print successful JSON to stdout and errors to stderr.
- [ ] Add a live OpenAI smoke test gated only by `RUN_LIVE_RAG_TEST=1`; lazy runtime imports inside the test, app-engine session and real client, no destructive DB setup. Default skipped; do not auto-run paid tests. Model/account compatibility remains live unverified until the operator runs it.

## Acceptance Criteria

- A caller can invoke the stateless typed Python function and CLI for one handbook question; no HTTP route, conversation history, or answer persistence is added.
- The service resolves the newest completed `heading_aware` run, errors on missing/mismatched latest run without fallback, retrieves at most five chunks, and returns the selected run ID.
- Zero retrieved chunks returns `abstained` without a generation request; a nonempty result makes at most one OpenAI Responses request, with no automatic retry.
- The model receives only retrieved evidence as untrusted context. Claims are evidence-only, atomic, and structurally linked to retrieved chunk IDs; the app builds accurate available provenance and rejects invalid IDs. No independent entailment guarantee is claimed.
- The configured input budget estimates the complete serialized generation request, including chunk identifiers, headings, delimiters, schema/format overhead, prompt and question; add 256 framing tokens and multiply by 1.2 at default margin .20. Estimated input plus output allowance fits the operator-configured context window (default 1050000), not a guaranteed provider limit. Unknown model mapping uses the explicitly unverified `o200k_base` fallback by user override. Actual input/output usage is compared to estimates in metadata-only logs; provider context-limit rejection remains an operational error. No chunk is truncated; prompt-only exhaustion or an oversized first chunk yields a safe operational error without a generation call.
- JSON output conforms to the typed contract; human output renders claims and numbered citations. All four content statuses follow their defined semantics, including cited partial clarification.
- Operational failures are distinct from content statuses, sanitized, logged without question/context/completion content, and produce nonzero CLI exit.
- Offline tests cover status cross-field invariants, outcome paths, prompt construction/security boundaries, citation integrity against included context, serialized-budget edges, retries disabled on injected clients, CLI behavior, and error sanitization; a mocked model does not establish model resistance to injection. Live compatibility and behavioral smoke tests are opt-in.

## Testing

- Resolver/retrieval tests: newest completed run, missing snapshot, model mismatch/no fallback, empty chunks, and `top_k=5`.
- Model tests: every status-specific invariant, including `answered` with zero claims, `partial` without unanswered parts, `clarification_needed` without a question, `abstained` with claims/citations, duplicate IDs, and factual assertions in explanatory fields.
- Service tests with fake retrieval/Responses client: all four statuses, IDs-only model citations, deduped provenance, citation to retrieved-but-excluded chunk, exact referenced citation list, missing source identity, unknown-model `o200k_base` estimation fallback and encoding-load failure, complete serialized request/schema/framing256 budget with default times1.2 margin, prompt-only exhaustion, estimated-input/output context bound, actual usage comparison metadata, zero calls on empty retrieval or budget errors, one call maximum, retries disabled even for injected client, context-limit/refusal/provider/schema/incomplete-output errors.
- Injection tests: offline tests verify prompt construction and security boundaries only; they do not prove model resistance. Only included retrieved chunk IDs are accepted. Opt-in live behavioral tests may assess the selected model's response to adversarial instructions.
- CLI tests: empty question, lazy imports after argparse, human inline references/provenance and optional outcome fields, typed JSON rendering, stable mode-matched sanitized stderr and 0/1/2 exit status; fakes only, no settings-file reads, real DB or OpenAI calls. Live smoke defaults to skipped and uses the application session/real client only when `RUN_LIVE_RAG_TEST=1`; never auto-run paid tests.
- Run focused RAG and ingestion retrieval tests plus Ruff/Pylance checks; no required paid API test in normal CI.

## Logging

Log operational metadata only at every level. Do not log raw question, prompt, retrieved content, model completion, or answer text, including DEBUG. Use structured Loguru fields; retrieval continues its existing safe metadata logging.

| Event | Level | Fields | Example |
|---|---|---|---|
| RAG started | `info` | `request_id`, `strategy`, `top_k`, `question_chars`, `model` | `{"request_id":"rag-7f2","strategy":"heading_aware","top_k":5,"question_chars":48,"model":"gpt-6-luna"}` |
| Run selected | `debug` | `request_id`, `run_id`, `strategy`, `selection` | `{"request_id":"rag-7f2","run_id":"7d2f3ac0-9f4d-4c65-a7a5-52f747ad0280","strategy":"heading_aware","selection":"latest_completed"}` |
| Context prepared | `debug` | `request_id`, `retrieved_chunk_ids`, `included_chunk_ids`, `serialized_input_tokens`, `schema_tokens`, `framing_reserve_tokens`, `output_tokens_reserved`, `model_context_window` | `{"request_id":"rag-7f2","retrieved_chunk_ids":["c-1","c-2"],"included_chunk_ids":["c-1"],"serialized_input_tokens":12140,"schema_tokens":860,"framing_reserve_tokens":256,"output_tokens_reserved":4096,"model_context_window":1050000}` |
| Tokenizer/accounting | `debug` | `request_id`, `encoding`, `tokenizer_fallback`, `serialized_tokens`, `estimated_input_tokens`, `safety_margin` | `{"request_id":"rag-7f2","encoding":"o200k_base","tokenizer_fallback":true,"serialized_tokens":12140,"estimated_input_tokens":14876,"safety_margin":0.20}` |
| Actual usage comparison | `info` | `request_id`, `actual_input_tokens`, `actual_output_tokens`, `estimated_input_tokens`, `estimate_error_tokens`, `estimate_exceeded`, `actual_input_limit_exceeded` | `{"request_id":"rag-7f2","actual_input_tokens":12500,"actual_output_tokens":300,"estimated_input_tokens":14876,"estimate_error_tokens":-2376,"estimate_exceeded":false,"actual_input_limit_exceeded":false}` |
| Generation request | `debug` | `request_id`, `model`, `input_tokens`, `max_output_tokens`, `retry_count` | `{"request_id":"rag-7f2","model":"gpt-6-luna","input_tokens":12140,"max_output_tokens":4096,"retry_count":0}` |
| Generation completed | `info` | `request_id`, `model`, `status`, `claim_count`, `citation_count`, `duration_ms` | `{"request_id":"rag-7f2","model":"gpt-6-luna","status":"partial","claim_count":2,"citation_count":2,"duration_ms":842}` |
| Operational failure | `error` | `request_id`, `operation`, `reason_code`, `duration_ms` | `{"request_id":"rag-7f2","operation":"generation","reason_code":"provider_server_error","duration_ms":510}` |
| Function exit | `debug` | `request_id`, `function_name`, `status_or_error`, `run_id`, `duration_ms` | `{"request_id":"rag-7f2","function_name":"answer_question","status_or_error":"answered","run_id":"7d2f3ac0-9f4d-4c65-a7a5-52f747ad0280","duration_ms":870}` |

## Edge Cases

- No completed snapshot vs. selected snapshot with zero chunks: error vs. abstention, respectively.
- Newest run has an incompatible embedding model: error; do not search an older run.
- Prompt, question, schema, and framing reserve exhaust the input budget before any chunk: context-budget error; no generation request.
- The first ranked chunk cannot fit, or input plus output allowance and reserve exceed the model context window: context-budget error; no truncation or lower-ranked substitution.
- A later chunk does not fit after a ranked prefix: stop at that chunk; do not skip it to include lower-ranked chunks.
- A cited chunk has blank title and path: reject citation; empty heading/span metadata is allowed.
- A claim cites a retrieved chunk excluded from the generation prompt, contains duplicate IDs, or leaves an unreferenced citation record: reject model output.
- Model requests clarification while supporting some claims: return clarification with cited claims; ambiguity status takes precedence over partial.
- Model returns no parsed output, refusal, incomplete output due to max-output limit, invalid status/field combination, unknown citation ID, or unsupported structured data: sanitized operational error.

## Risks & Unknowns

- Citation-to-claim support is model-proposed and structurally checked only; one-call constraint excludes independent entailment verification.
- `gpt-6-luna` API/model access and live Responses/Structured Outputs compatibility are account-dependent and currently unverified. Operator-owned live verification is appropriate before rollout, not an implementation/account-availability gate.
- The model/API/SDK/tokenizer combination may change. User override explicitly chooses unknown-model `o200k_base` estimation fallback, not strict tokenizer-mapping failure; the fallback must be labeled unverified and recorded in metadata.
- Locally counted input approximates provider token accounting; complete logical JSON/schema serialization plus framing256, times1.2 default margin, and estimated-input/output context-window checks reduce but cannot eliminate discrepancies. Neither the fallback nor the 1050000 configured window establishes real model capacity. Compare actual input/output usage metadata with estimates; provider context-limit rejection is an operational error, never an abstention.
- Prompt-injection robustness cannot be fully guaranteed by prompt framing or mocked tests; retain an opt-in live behavioral check.

## Out of Scope

- HTTP endpoint, conversational state/query rewriting, history or answer persistence.
- External guardrail/Model Armor invocation, separate LLM judge, automatic retry, similarity threshold, or independent citation-entailment verification.
- Changes to ingestion/chunking strategy or retrieval ranking beyond exposing latest-run resolution.
- RAG quality benchmark automation beyond deterministic acceptance tests and an opt-in live smoke test.

## Docs to Update
