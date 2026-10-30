# Build the Engineering Handbook Markdown Parser

> 🌿 **Branch:** `feat/markdown-parser` · 📅 **Date:** 2026-10-30

## Problem & Solution
**Problem:** Phase 2 step 7 has no parser in `backend/app/ingestion`; the handbook Markdown cannot yet be represented as structured source content for the later chunking step.

**Solution:** Add a handbook-topic Markdown parser that accepts text or a UTF-8 file and returns typed, source-located dataclasses. Keep persistence, chunking, hashing, and embeddings outside this parser.

## Decisions

| Type | Decision | Choice | Why |
|---|---|---|---|
| Constraint | Scope and responsibility | One engineering-handbook topic per parse; no DB writes, chunking, hashing, or embeddings | Matches Phase 2 step 7 boundary and keeps parsing independently testable |
| Constraint | Existing persistence model | Parser results are separate from `KnowledgeDocument` / `KnowledgeChunk` SQLModel records | Source sections and parser blocks are not persisted chunks |
| Constraint | Logging | Use Loguru via `app.core.logger.app_logger`; omit source text and user-controlled identifiers | Matches repo convention and avoids leaking potentially sensitive handbook content or paths |
| Choice | Parser engine | `MarkdownIt("gfm-like", {"html": True})` plus `mdit_py_plugins.tasklists.tasklists_plugin`; no exact GitHub parity | GFM-like enables tables, strikethrough, and linkify; task-list plugin adds checkbox tokens; HTML parsing preserves raw HTML tokens |
| Choice | Input/API | `parse_markdown(text, source_path=None)` and `parse_markdown_file(path)`; strict UTF-8 | Supports in-memory tests and file ingestion without ambiguous input detection |
| Choice | Output structure | Typed dataclasses: document introduction plus nested sections with one ordered stream of blocks/child sections | Preserves source order and heading context without returning library tokens |
| Constraint | Empty content | An introduction or section may contain no meaningful body blocks and remains valid parser output; downstream chunking/ingestion decides whether content is sufficient for embedding | Keeps content-quality policy out of syntax parsing |
| Choice | Markdown fidelity | Preserve specified typed block/inline constructs, table cells and task state; unknown extensions fall back to text | Retains retrieval-relevant semantics without promising full GFM/extension parity |
| Choice | Validation | Exactly one H1, at least one H2, no nonblank content before H1; allow blank lines/comments | Enforces handbook shape while accepting benign preamble formatting |
| Choice | Source provenance | 1-based inclusive section and top-level block ranges; nested blocks inherit parent range; supplied path stays in result but is not logged | Enables traceability with block maps without custom inline source maps or path disclosure in logs |
| Choice | Errors | `MarkdownParseError` for empty/invalid structure; file and UTF-8 errors propagate unchanged | Separates document-shape errors from ordinary I/O failures |
| Choice | Dependencies | Declare `markdown-it-py[linkify]` and `mdit-py-plugins` directly in `backend/pyproject.toml`; refresh `backend/uv.lock` | Parser runtime dependencies must be explicit and locked |

## Architecture

```text
Markdown text ───────────────────────────┐
                                         ▼
File path ─► strict UTF-8 read ─► parse_markdown(text, source_path)
                                         │
                                         ▼
            MarkdownIt("gfm-like", html=True) + tasklists_plugin
                                         │ tokens + block line maps
                                         ▼
                       typed dataclass conversion + validation
                                         │
                                         ▼
                           ParsedDocument (no persistence)
                                         │
                              later chunking step
```

## Code Shape

- `markdown_models.py` defines `SourceRange(start_line, end_line)` (one-based, inclusive), `ParsedDocument`, `Section`, and the block/inline dataclasses/unions.
- `markdown_parser.py` defines `MarkdownParseError`, parser configuration, validation, token conversion, and the parser entry points.
- `ParsedDocument(title, source_path, introduction, sections)`.
- `Section(heading, level, heading_path, source_range, children)`; `children` is one ordered sequence of `Block | Section`.
- `Block` and `Inline` are tagged unions of distinct dataclasses, not SQLModel or parser-library tokens.
- Inline nodes: text, emphasis, strong, code span, link (destination + children), image (destination + alt text), strikethrough, soft/hard break, and opaque raw HTML.
- Block nodes: paragraph (inline nodes), list (ordered flag/start/items), list item (nested blocks + optional checked state), code block (verbatim code + optional fence language), table (header/body cell arrays of inline nodes), blockquote (nested blocks), thematic break, and opaque raw HTML.
- Configure `MarkdownIt("gfm-like", {"html": True})` and `.use(tasklists_plugin)`. The `gfm-like` preset enables tables, strikethrough, and linkify; the linkify extra supplies `linkify-it-py`. The task-list plugin injects checkbox `html_inline` tokens and marks list-item tokens; convert only plugin-generated checkbox tokens into `checked: bool`, and omit those synthetic tokens from raw-HTML content.
- Document introduction is an ordered block list. H1 is the plain-text document title; H2–H6 create sections. Each section's heading path is plain text from H1 through itself.
- `parse_markdown_file(path)` reads the path and delegates with its supplied path string. Do not resolve/fetch links or rewrite paths.

## Validation Rules

- Reject empty/whitespace-only input, missing or multiple H1s, missing H2, and nonblank content before H1 with `MarkdownParseError`.
- Ignore blank lines and HTML comments before H1.
- Preserve empty sections and duplicate section titles in source order.
- Support headings H2–H6; each heading owns subsequent content through the next same-or-higher-level heading.
- Use markdown-it-py source block maps; convert zero-based, end-exclusive maps to one-based inclusive ranges. Section ranges include descendant sections and all intervening blank lines through the line before the next same-or-higher-level heading. The final section ends at the final logical source line, including trailing blank-only lines; a terminal newline alone does not add a line.
- Assign ranges to sections and top-level blocks. Nested list/blockquote blocks inherit their containing top-level block range; inline nodes need no range.
- File input is strict UTF-8. Propagate `FileNotFoundError` and `UnicodeDecodeError`; do not wrap these as parse errors.
- Preserve HTML as opaque source; do not render, sanitize, or filter it here. Do not follow links.
- Before H1, allow blank lines and HTML comments only; reject visible HTML and other nonblank Markdown content.
- For GFM tables, escaped pipes (`\\|`) do not split cells, including in inline spans; preserve empty cells. Unescaped pipes delimit cells, including pipes inside code spans.
- A skipped heading level nests beneath the nearest preceding section with a lower heading level (e.g. H4 directly under H2); never invent missing headings.

## Implementation Plan

### Phase 1: Implement the handbook parser (single feature commit)
| File | What changes |
|---|---|
| `backend/app/ingestion/__init__.py` | Export parser entry points, error, and public dataclasses |
| `backend/app/ingestion/markdown_models.py` | Define `SourceRange`, parsed document/section dataclasses, and typed block/inline node dataclasses/unions |
| `backend/app/ingestion/markdown_parser.py` | Define `MarkdownParseError`; configure the exact markdown-it-py preset/plugins; parse/validate text and files; convert tokens, task state, sections, and source ranges |
| `backend/pyproject.toml` | Declare `markdown-it-py[linkify]` and `mdit-py-plugins` directly |
| `backend/uv.lock` | Lock the direct parser/plugin dependencies |
| `backend/tests/ingestion/test_markdown_parser.py` | Add tests for all handbook topics, synthetic constructs, ordering, ranges, and invalid input |

- [ ] Implement the text and file APIs; preserve caller-supplied path form and strict UTF-8 behavior.
- [ ] Convert tokens to the agreed dataclass structure, preserving block order and selected GFM semantics.
- [ ] Validate handbook title/section rules and map source ranges.
- [ ] Extract checked state from task-list plugin tokens; verify the locked plugin versions and configuration.
- [ ] Add output-focused tests and verify no parser path accesses the database or generates embeddings.

## Acceptance Criteria

- Both public entry points return the same parsed structure for equivalent text/file input, with file input carrying its supplied path.
- Every existing engineering-handbook topic page parses with its H1 title, H2 sections, heading paths, and source ranges.
- Section/block order matches source order, including skipped heading levels and interleaved nested sections; empty and repeated-title sections remain represented.
- Empty introductions and sections remain valid parsed structures. No minimum-content or embedding-suitability checks are performed by the parser; a future ingestion/chunking layer owns that decision.
- Tables (including escaped pipes and empty cells), nested ordered/unordered/task lists with checkbox state, code fences, inline formatting/links/images, strikethrough, blockquotes, thematic breaks, and opaque HTML retain the selected structure.
- Input validation raises `MarkdownParseError` for empty text, invalid H1 count, missing H2, and forbidden pre-title content; blank lines/comments before H1 are accepted.
- UTF-8 decode and filesystem errors propagate unchanged; paths are not resolved and links are not followed.
- Tests pass; Ruff check/format pass; parser dependencies are direct project dependencies and locked.
- No database writes, chunk creation, content hashing, or embedding generation occur in parser APIs.

## Testing

- Parse all 12 handbook topic files; assert title, section hierarchy, heading paths, and valid line ranges.
- Synthetic fixtures: H1 followed immediately by an empty H2 section; H2→H4 with no H3; H2 containing only H3; paragraphs after H3; interleaved sections; empty/duplicate H2s; nested task lists; headings inside fenced code; nested lists and ordered-list start; GFM tables with escaped pipes (including inline code), empty cells, and inline content; fenced code/language/whitespace; links, images, emphasis, code spans, strikethrough, soft/hard breaks; blockquotes, thematic breaks, raw HTML; unknown extension syntax as text.
- Verify exact source order and one-based inclusive line conversions for LF and CRLF, including blank lines before the next heading, trailing blank lines at EOF, section spans across descendants, nested-block range inheritance, and code-fence heading text.
- Verify invalid documents (empty, missing/multiple H1, no H2, visible HTML or other content before H1) raise `MarkdownParseError`; blank lines and HTML-comment preambles pass.
- Verify file API strict UTF-8 and unchanged propagation of missing-file/decode errors; verify output preserves the supplied relative/absolute path representation.

## Logging

Use structured Loguru events through `app.core.logger.app_logger`. Do not log Markdown bodies, code contents, inline text, titles, headings, supplied paths, exception messages, or complete parsed output.

| Event | Level | Fields | Example |
|---|---|---|---|
| Parse entry | `debug` | `function`, `source_kind`, `input_chars` | `{function: "parse_markdown", source_kind: "file", input_chars: 2840}` |
| Parse success | `debug` | `function`, `section_count`, `source_ranges`, `block_types` | `{function: "parse_markdown", section_count: 10, source_ranges: [[3, 10], [11, 19]], block_types: ["paragraph", "list"]}` |
| Invalid document structure | `warning` | `reason_code`, `line` | `{reason_code: "content_before_h1", line: 1}` |
| File/decode failure | `error` | `error_type` | `{error_type: "UnicodeDecodeError"}` |

## Edge Cases

- HTML comments and blank lines before H1 are allowed; other pre-title content is rejected.
- Repeated headings and empty sections remain distinct and in order.
- An introduction containing only blank space and a section with a heading but no body both parse successfully; parser validation checks document structure, not whether chunks can be generated.
- A skipped heading level attaches to the nearest preceding lower-level section; no missing heading is synthesized. Content after H3 belongs to that H3 until a same-or-higher heading.
- Nested sections may occur between blocks; preserve their interleaving.
- Parser token line maps are end-exclusive and zero-based; conversion must not shift final lines. Blank lines before a following heading belong to the preceding section; the final section includes trailing blank-only lines through EOF.
- CRLF and LF inputs produce equivalent logical line ranges.
- Escaped table pipes remain inside cells; empty cells remain represented. Unescaped pipes, including inside code spans, delimit cells under GFM.
- Nested list/blockquote child ranges inherit the containing top-level block range.
- Task-list plugin checkbox tokens become checked state; synthetic HTML checkbox tokens are not preserved as authored HTML.
- Opaque HTML is preserved but must not be rendered by this feature.
- Logs contain only structural, non-content metadata; paths, headings, titles, and exception messages are excluded.

## Risks & Unknowns

- `markdown-it-py`'s `gfm-like` mode is approximate; tests must assert explicitly supported constructs, not GitHub rendering parity.
- Nested block source maps are not first-class in the selected approach; inherited ranges are coarser than per-child positions.
- Opaque HTML must remain non-rendered until a separately reviewed sanitization/rendering boundary exists.
- The task-list plugin represents checkbox state as synthetic HTML tokens; conversion must distinguish these plugin-generated tokens from authored raw HTML.
- The declared plugin versions must remain compatible with markdown-it-py 4.x and its token API; verify through lockfile resolution and focused tests.

## Out of Scope

- File discovery/batch ingestion and README index parsing.
- Database persistence, updating `KnowledgeDocument`, or creating `KnowledgeChunk` rows.
- Chunking strategy, content hashing, embedding generation, vector search, citations, or RAG.
- Following/resolving links, rendering HTML, or sanitizing HTML.
- Exact GitHub GFM parity or arbitrary Markdown extensions.

## Docs to Update

- N/A. No root `INDEX.md` exists; this feature does not otherwise require changes to existing docs. The parser plan is the new specification.
