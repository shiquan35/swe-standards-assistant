# Build the Initial Markdown Chunking Strategy

> 🌿 **Branch:** `feat/initial-chunking-strategy` · 📅 **Date:** 2026-10-30

## Problem & Solution
**Problem:** The parser produces a typed `ParsedDocument`, but there is no serializer or chunker to turn it into consistently sized retrieval candidates. The empty `backend/app/ingestion/chunker.py` is the intended starting point.

**Solution:** Add deterministic canonical-Markdown serialization and three interchangeable, configurable strategies that return transient `ChunkCandidate` values with token counts and source metadata. Keep embeddings and persistence out of this feature.

## Decisions

| Type | Decision | Choice | Why |
|---|---|---|---|
| Constraint | Parser boundary | Consume existing `ParsedDocument`/AST; do not make parsing perform chunking | Preserves Phase 2 step 7 separation |
| Constraint | Persistence | No SQLModel records, database calls, IDs, embeddings, or migrations | Phase 2 step 8 produces transient candidates only |
| Constraint | Model/tokenizer | OpenAI `text-embedding-3-small`; `cl100k_base` via `tiktoken` | Matches README and OpenAI embedding documentation; 500 is below the model's 8192-token input limit |
| Choice | Output term | `ChunkCandidate`, distinct from persisted `Chunk` | Matches the project glossary and keeps chunking independent of persistence |
| Choice | Shared API | All strategies implement one `chunk(document, config, tokenizer)` interface and return ordered candidates | Allows strategies to be swapped without changing consumers |
| Choice | Defaults | A: max 500/overlap 0; B: max 500/overlap 100; C: max 500/overlap 100 | Establishes the requested baseline profiles while retaining configurable values |
| Choice | Canonical content | Serialize typed AST nodes into deterministic Markdown; preserve represented semantics, not original bytes/formatting | Parser output is structured and does not retain source text |
| Choice | Fixed strategies | A/B tokenize the whole serialized document, including title, introduction and headings; they may cross heading paths and split Markdown syntax; do not inject headings per window | Keeps A/B simple, comparable baselines |
| Choice | Heading-aware | Keep source-contiguous runs within a single heading path; process introduction under `[document title]`; skip empty/heading-only sections | Uses parser hierarchy without merging content across nested sections |
| Choice | Oversized content | C packs whole blocks first, prefers list-item/table-row/code-line/paragraph boundaries, then falls back to strict token windows; repeat table headers when splitting tables | Preserves structure when possible while enforcing the hard maximum |
| Choice | Heading context | C prefixes every candidate with the full heading breadcrumb where feasible, including unsplit candidates; count it toward the maximum; reduce overlap first, then omit the prefix if necessary | Makes heading context consistent without sacrificing content or the hard limit |
| Choice | Overlap | A has none; B targets the preceding source-text suffix; C prefers natural source boundaries within the target and never overlaps generated context; record actual overlap | Keeps baseline windows simple and C structure-aware; exact 100-token overlap is not always feasible |
| Choice | Provenance | Carry optional `source_path`, ordered heading paths and ordered 1-based inclusive source spans; preserve only ranges available from the AST | Supports later attribution without re-parsing or changing parser-owned data |
| Choice | Logging | Structured safe summaries only; never log source content, title, headings, or path | Follows parser logging constraints and avoids leaking handbook content |

## Architecture

```text
ParsedDocument
      │
      ▼
Canonical Markdown serializer ──► serialized text + source/heading segment map
      │                                           │
      ├── Fixed 500/0 ────────────────────────────┤
      ├── Fixed 500/100 ──────────────────────────┤──► ordered ChunkCandidate list
      └── Heading-aware 500/100 ──────────────────┘
                                                  │
                         cl100k_base tokenizer ◄──┘

No embedding API or database is called.
```

## Code Shape

- `ChunkingConfig(max_tokens=500, overlap_tokens=...)`; validate `max_tokens > 0` and `0 <= overlap_tokens < max_tokens`.
- `Chunker` protocol: `chunk(document: ParsedDocument, config: ChunkingConfig, tokenizer: Tokenizer) -> list[ChunkCandidate]`.
- Provide fixed-no-overlap, fixed-overlap and heading-aware implementations with the agreed default profiles.
- `ChunkCandidate`: zero-based `ordinal`, strategy identifier, canonical `content`, `token_count`, optional `source_path`, ordered distinct `heading_paths`, and ordered `source_spans: list[SourceRange]`.
- Also expose `parts: list[ChunkPart]`, `actual_overlap_tokens: int`, and `heading_prefix_omitted: bool`. `ChunkPart` records half-open Python-character offsets `output_start/output_end`, a role (`source`, `overlap`, or `context`), optional half-open `canonical_start/canonical_end`, and optional context kind (`heading_breadcrumb`, `table_header`, or `markdown_wrapper`). Source/overlap parts map exactly to canonical text; context parts have no canonical coverage offsets. Parts partition candidate content without gaps.
- `SerializedMarkdown`: canonical `text` plus ordered character segments mapping each emitted range to its heading path and optional source range. Use section start lines for section heading spans and existing block ranges for blocks. The parser does not expose an H1 title range; do not invent one.
- `Tokenizer` is backed by `tiktoken` `cl100k_base`; count literal text with special-token recognition disabled, including authored strings such as `<|endoftext|>`. All counts refer to independently encoding the exact emitted string, not adding independently measured part counts.
- Implement the serializer as a visitor over existing `Inline` and `Block` unions. Preserve emphasis, strong, strike, links/destinations, images/alt text, breaks, opaque HTML, ordered/list/task state, code/language, tables, quotes, thematic breaks, and nested `HeadingBlock`s. Emit heading markers from document/section hierarchy. Formatting is canonical, not byte-identical to source.

### Deterministic Unicode-safe splitting

The following finite search defines correctness; implementations may optimize it only if they preserve its result. Operate on canonical Python strings at Unicode code-point boundaries, never decode arbitrary token slices with replacement. Do not normalize Unicode, strip whitespace, or discard separators. Grapheme clusters may span candidates; Unicode scalar values may not.

1. Maintain a cursor `p` at the first uncovered canonical character in the current stream/run. Choose overlap start `s <= p` using the rules below; the new source interval ends at `e > p`.
2. With the chosen prefix, wrappers and overlap, enumerate eligible end offsets in descending order and re-encode the **complete rendered candidate**. Select the greatest eligible `e` whose count is at most `max_tokens`. A/B consider every code-point boundary; C first considers natural boundaries, then finer boundaries only when its next structural unit cannot fit.
3. If no end advances past `p`, shrink overlap through eligible suffixes toward zero, then omit generated table headers/wrappers if they prevent progress. For C, retain the heading prefix if any advancing end fits without overlap or wrappers; otherwise omit the whole prefix and record the omission. Retry with no context or overlap before declaring failure.
4. Emit only a candidate covering at least one previously uncovered character; set `p = e`. Stop immediately at the end of the stream/run, without a trailing overlap-only candidate. This guarantees finite forward progress and complete eligible-content coverage on success.
5. Encoding lengths need not be monotonic as text is appended: do not rely on binary search, summed token counts, or assuming a fitting prefix means every shorter prefix fits. Exhaust all advancing code-point boundaries before failure. If none fits even without context/overlap, raise `ChunkingError(reason_code="token_budget_unrepresentable")`; return no partial list. A tiny valid budget can be smaller than the encoding of a single Unicode character, so universal successful splitting for every positive budget is impossible. Reject lone surrogate characters with `ChunkingError(reason_code="invalid_unicode")` before serialization/tokenization.

### Strategy C packing, context and overlap

- Traverse source-contiguous direct-body runs in document order. A child section ends its parent's run; returning to that parent starts a fresh run, even if its heading path is identical. Never overlap across runs, sections, introductions or documents.
- Prefix **every** C candidate with the full path: one ATX heading per ancestor using its actual level (H1 for the document), separated by `\n`, then `\n\n` before the body. Preserve skipped levels. This is generated context, not a second occurrence of original outline content. Do not emit a duplicate current heading as source body.
- Greedily pack the longest sequence of complete blocks that fits. When the next block alone cannot fit with its feasible breadcrumb, use list-item, table-row, code-line, blockquote-child or paragraph boundaries as appropriate; an oversized smallest unit uses the code-point-safe token-budget search above. Exact Markdown validity is best effort, not a hard postcondition.
- For a table continuation, insert its canonical header and delimiter as `context` before the continuing rows. The table's first header occurrence remains `source`; repeated headers do not count as overlap. Likewise tag any repeated code fences/list/quote wrappers as `context`, and count all generated text toward the maximum.
- The first candidate of each run has zero overlap. If the run needs further candidates, overlap is a suffix of the previous candidate's **original canonical body interval**, excluding breadcrumb, repeated headers and all other context. It may include text previously marked overlap but must end exactly at cursor `p`; its start cannot precede the previous candidate's earliest mapped body character.
- Enumerate natural suffix starts (block boundaries, or the finer structural boundaries used to split an oversized block) whose independently encoded suffix is at most `overlap_tokens`. Prefer the suffix with the greatest token count; ties use the earliest start offset. Zero overlap is always available. Within a token-fallback fragment, use code-point suffix starts instead. Do not cut an otherwise intact block merely to reach 100 tokens; actual overlap may be much smaller or zero.
- If overlap prevents the next complete unit from fitting, reduce it using that same ordering before fragmenting the unit. Once overlap is zero, split the oversized unit by the hierarchy above. Heading-prefix fallback follows the Unicode-safe algorithm: omit it only if it prevents **any** new character from fitting, not just because an intact block is large.
- B uses code-point suffix starts with the same at-most-target ranking, without structural preferences or generated context. A always uses `s = p`. Neither strategy adds contextual headings.
- `actual_overlap_tokens` is the independent encoding length of the canonical suffix `[s:p]`, zero when absent. It excludes all generated context; token counts of final candidates can differ from sums of their parts due to retokenization. Record a separate overlap part mapping `[s:p]`; newly consumed `[p:e]` is source. The requested 100 is a target, never a reason to exceed the maximum or stall.

### Canonical-content coverage contract

- “Original” here means the serializer's canonical representation of AST content, not original Markdown bytes. Freeze canonical text and its offset map before splitting. A/B's eligible interval is the entire canonical document, including all headings and serializer separators.
- C's eligible intervals are the canonical direct-body runs (including separators between blocks within a run). Outline H1/section headings and separators outside body runs are explicitly metadata/context-only, not missing body content; `HeadingBlock` nodes inside blocks remain body content. Empty outline sections therefore need not produce candidates.
- Every source/overlap part's output substring must equal the canonical substring at its mapped offsets. Context parts carry explicit kinds and are ignored by coverage checks; repeating a heading or table header must never masquerade as consuming new source.
- Verify that source parts, in traversal order, partition the eligible intervals exactly once without gaps, skipped characters or duplicate consumption. Concatenating source parts must reconstruct those intervals exactly. Verify overlap parts separately as the preceding run/stream suffix and check `actual_overlap_tokens`; never infer coverage by substring search or deduplication (identical prose and repeated headings are valid).
- Source spans are coarse citations derived from intersected AST segments, not the coverage proof. Retain them in source order without merging across skipped source content. Context may reference existing heading/table provenance but must not invent a source line or widen canonical coverage. Validate candidate content as the exact concatenation of all its parts.

## Validation Rules

- `max_tokens` is a positive integer; overlap is non-negative and strictly less than the maximum.
- Every emitted candidate has `token_count == len(tokenizer.encode(content))` and `token_count <= max_tokens`.
- Strategies emit candidates in source order; actual overlap follows the source-suffix rules above and is recorded, never assumed to equal the configured target.
- Fixed strategies serialize the whole document and may cross paths. Their `heading_paths` records all contributing paths in first-seen order; no heading breadcrumb is injected per window.
- Heading-aware candidates do not mix paths or source-discontiguous parent runs. Introduction candidates use `[document.title]`; empty/heading-only sections emit none.
- Source spans are ordered and derived only from contributing serialized segments; repeated headings/overlap may repeat spans across candidates. Do not claim character-level source precision inside parser blocks.
- Invalid configuration raises `ValueError`; the parser remains unchanged and owns document-shape validation.
- Empty input has two explicit boundaries: `parse_markdown("")` continues to raise `MarkdownParseError`; a directly supplied empty `ParsedDocument` with no body blocks or sections returns `[]` for all strategies (do not create a title-only window). A nonempty heading-only tree can produce canonical-heading windows for A/B, while C returns `[]`. If the full eligible stream is whitespace-only, return `[]`; C treats a run with only whitespace serialization as empty. Within any nonblank eligible stream/run, all whitespace remains covered even if a very small budget requires a whitespace-only window. Never emit zero-length or context-only candidates.
- Successful candidates have contiguous zero-based ordinals and at least one new eligible source character; a failure raises before returning any result. No parser AST mutation, source file rereads or network access is needed for chunking.

## Implementation Plan

### Phase 1: Canonical serialization and candidate contract
| File | What changes |
|---|---|
| `backend/app/ingestion/markdown_serializer.py` | Add deterministic AST-to-Markdown serialization and source/heading segment mapping |
| `backend/app/ingestion/chunk_models.py` | Add `ChunkingConfig`, `ChunkCandidate`, `ChunkPart`, `ChunkingError`, serialized segment types, and tokenizer/chunker protocols |
| `backend/app/ingestion/tokenizer.py` | Add the `cl100k_base` adapter and exact full-string token counting |
| `backend/app/ingestion/__init__.py` | Export the public chunking types and entry points |
| `backend/pyproject.toml` | Add `tiktoken` as a direct dependency |
| `backend/uv.lock` | Lock the tokenizer dependency |
| `backend/tests/ingestion/test_markdown_serializer.py` | Test every supported AST node, ordering, canonical output, and segment provenance |

- [ ] Define canonical representations for all parser `Inline`/`Block` node types, eligible coverage intervals and generated-context roles; map output segments to available provenance.
- [ ] Add the tokenizer adapter using `tiktoken` with `cl100k_base`.

### Phase 2: Strategies, checks, and integration tests
| File | What changes |
|---|---|
| `backend/app/ingestion/chunker.py` | Implement shared strategy interface and the three strategies |
| `backend/tests/ingestion/test_chunker.py` | Add strategy, boundary, quality, provenance, and corpus tests |
| `backend/app/functions/chunk_handbook.py` | Add an argparse inspection CLI using existing parser and chunking APIs |
| `backend/tests/ingestion/test_chunk_handbook.py` | Verify CLI output, argument validation, strategy selection and empty-result handling |

- [ ] Implement A/B whole-stream token windows and C section/run-aware packing, explicit overlap accounting, every-candidate breadcrumbs and deterministic Unicode-safe fallback.
- [ ] Add output-based quality validation and structured safe logging.
- [ ] Add `python -m app.functions.chunk_handbook [path] --strategy {fixed,fixed_overlap,heading_aware} --max-tokens 500 --overlap-tokens N`. Default to the API-standards path used by `parse_handbook.py`, `heading_aware`, 500 tokens and strategy-specific overlap (0 for fixed, 100 otherwise); reject nonzero overlap for fixed. Display each ordinal, strategy, content verbatim, measured tokens, actual overlap, heading paths, source spans and prefix-omission flag. Print a clear zero-candidate message; invalid arguments/processing failures exit nonzero. Use stdout intentionally (`# noqa: T201`), not content-bearing logs; no file output or external services.
- [ ] Run parser regression tests, chunker/serializer tests, Ruff, and tests over all 12 handbook topics.

## Acceptance Criteria

- Each strategy consumes the existing `ParsedDocument` and returns the same `ChunkCandidate` shape in deterministic source order.
- A defaults to 500 tokens with no overlap; B to 500/100; C to a 500 maximum with 100 overlap when splitting oversized content; all values are configurable.
- The serializer produces canonical Markdown representing supported AST semantics. A/B candidates are text windows and need not be independently valid Markdown; all candidates respect their configured token maximum.
- A/B process one whole-document stream and do not inject missing heading context; C respects heading paths, contiguous runs, introduction ownership, and empty-section behavior as specified.
- Candidate metadata includes token count, strategy, optional document path, heading paths and available source spans; source spans do not claim precision unsupported by parser nodes.
- Every successful split preserves Unicode and canonical coverage under the hard maximum, and every candidate advances the source cursor. Impossible tiny budgets fail explicitly without partial results or replacement characters.
- C includes the full breadcrumb in every candidate where feasible; overlap counts exclude generated context, respect natural boundaries, and expose actual rather than assumed overlap.
- Coverage validation reconstructs eligible canonical intervals from source parts exactly once and checks overlap/context separately; repeated prose, headings and table headers cannot hide loss or duplication.
- Empty ASTs and heading-only documents follow the specified per-strategy behavior; the inspection CLI displays content and quality metadata for all three strategies without external services.
- Automated tests verify serialization, token counts, overlap, ordered coverage, block fallback, metadata integrity, and deterministic output without database or embedding services.
- Existing parser tests and Ruff checks pass; all 12 handbook topic documents can be chunked by all strategies.

## Testing

- Serializer fixtures cover each inline/block type, nested sections, mixed parent blocks and subsections, task state, links, code, tables, HTML, and stable canonical output.
- Strategy fixtures cover empty/short/exact-limit/oversized content, section boundaries, repeated/skipped headings, introduction, empty sections, oversized tables/code/lists, and Unicode split boundaries.
- Assert token counts against independently encoded full output, hard maxima, deterministic natural/character boundary choices, actual overlap and context exclusion. Include C unsplit and split runs, a previous short block below the overlap target, an intact block larger than the target, repeated table headers, and prefix/overlap budget competition.
- Verify coverage using canonical offset partitions, not text matching: repeated identical paragraphs, repeated outline headings, nested blocks, generated wrappers, table continuations, B overlap and C breadcrumbs must not disguise dropped/duplicated source characters.
- Exercise emoji, CJK, combining marks, literal special-token strings, lone surrogates, very small budgets, unrepresentable-budget failure, overlap almost equal to the maximum, and final tails. Assert termination, valid text, no normalization/replacement, no overlap-only outputs, no partial success, and no lost whitespace around nonblank content.
- Assert `[]` for directly supplied empty ASTs in all strategies, C heading-only trees and whitespace-only runs; retain the parser's rejection of empty source strings. Capture CLI stdout for every strategy, default/overridden options, full displayed content/metadata, zero results and failure exit status.
- Assert `source_path`, heading paths, ordered source spans, repeated overlap spans, and the known absence of an H1 source range.
- Run all 12 handbook topics through all strategies and validate output invariants; do not call OpenAI, a database, or retrieval evaluation.

## Logging

Use `app.core.logger.app_logger` structured events. Log safe configuration and structural metadata only; never log content, source paths, titles, heading text/paths, or complete candidates.

| Event | Level | Fields | Example |
|---|---|---|---|
| Chunk entry | `debug` | `strategy`, `max_tokens`, `overlap_tokens`, `section_count`, `block_types` | `{strategy: "fixed_overlap", max_tokens: 500, overlap_tokens: 100, section_count: 4, block_types: ["paragraph", "list", "table"]}` |
| Chunk success | `debug` | `strategy`, candidate token counts, source spans, heading depths | `{strategy: "heading_aware", token_counts: [438, 291], source_spans: [[[3, 8]], [[10, 14]]], heading_depths: [2, 3]}` |
| Invalid config | `warning` | `max_tokens`, `overlap_tokens`, `reason_code` | `{max_tokens: 500, overlap_tokens: 500, reason_code: "overlap_not_less_than_max"}` |
| Chunk failure | `error` | `strategy`, `error_type`, `reason_code` | `{strategy: "heading_aware", error_type: "ChunkingError", reason_code: "token_budget_unrepresentable"}` |

Include safe per-candidate overlap/prefix diagnostics, e.g. `{ordinal: 2, actual_overlap_tokens: 84, heading_prefix_omitted: false}`. The inspection CLI is an explicit user-requested stdout view of source content/paths, not an exception to the application's no-content-logging rule.

## Edge Cases

- Token boundaries can split UTF-8 characters; adjust overlap/split to preserve valid text and the hard maximum.
- A heading breadcrumb can consume the budget on any C candidate, including the first; reduce overlap, then omit the whole emitted breadcrumb while retaining full heading metadata. Repeated table headers/wrappers also yield if necessary to allow progress.
- A single list item, table row, code line, or paragraph may exceed the limit; after natural boundaries, token-window fallback remains mandatory.
- C must not combine parent content across an intervening subsection; keep separate source-contiguous runs.
- A/B can split Markdown constructs and can produce windows without embedded heading context; this is intentional baseline behavior.
- Empty ASTs, empty source strings and heading-only ASTs are distinct; honor the explicit empty-input rules rather than sending synthetic headings through every strategy indiscriminately.
- Parser ranges are coarse for nested list/quote children, and the H1 title has no source range; provenance must report only available spans.

## Risks & Unknowns

- Canonical Markdown is a deterministic representation, not a byte-for-byte reconstruction; its exact formatting rules must be pinned by serializer tests.
- `tiktoken` encoding boundaries require care so token slicing does not corrupt Unicode or make reported counts disagree with emitted strings.
- Exhaustive code-point endpoint search is a correctness reference and may be expensive for long runs. Bound work to the current stream/block unit where possible, cache exact counts, and preserve the specified result when optimizing; benchmark locally without adding retrieval evaluation.
- A/B content can lack heading context when a window starts within a section; C provides the context-aware comparison, but retrieval effectiveness is explicitly not measured here.
- The 500/100 profiles are initial baselines, not an empirically validated retrieval optimum.

## Out of Scope

- Embedding generation, OpenAI calls, database operations, SQLModel persistence, migrations, document discovery, hashing, vector search, RAG, citations, and retrieval-quality evaluation.
- Changes to parser validation or AST models; exact preservation of source Markdown bytes; independently valid Markdown for every fixed window.

## Docs to Update

No root `INDEX.md` exists, so the index check is skipped. No existing documentation updates are planned for this feature; this plan is the new specification.
