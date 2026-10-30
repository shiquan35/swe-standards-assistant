# Markdown Parser Grill: Questions and Decisions

This document records the questions asked during the parser-design grill, the options offered, the user's selection, and a brief rationale inferred from that selection. It captures the design discussion before implementation; it is not itself an implementation specification beyond the recorded choices.

## Scope and input

### 1. What Markdown should the parser target?
- General Markdown files — reusable parser; handbook as first fixture set.
- **Engineering handbook only — selected.** Rationale: scope the first parser to the current source corpus.
- Other — describe the input corpus.

### 2. What should the parser own in Phase 2 step 7?
- **Parse one document — selected.** Accept one file or text and return structured content; leave discovery, chunking, and embeddings to later components.
- Parse and chunk — produce chunk-ready or persisted `KnowledgeChunk` records.
- Batch ingestion — discover, parse, and coordinate persistence together.

### 3. Which handbook files should be parsed?
- **Topic pages only — selected.** Parse the 12 standards documents; README remains an index/discovery file.
- README and topic pages — parse all 13 files.
- Other — specify a different file-selection rule.

### 4. What should a path-based parser accept?
- File path — read UTF-8 Markdown and include path context.
- Markdown string — leave file I/O to the caller.
- **Both path and string — selected.** Support file convenience and text parsing APIs.

### 5. Should parsing from text accept a source path?
- **Optional source path — selected.** Preserve provenance when the caller has it, but allow in-memory text without one.
- No path for text — only file parses carry paths.
- Require path for both — always require source identity.

### 6. What encoding should file reads use?
- **UTF-8 strict — selected.** Invalid byte sequences should raise rather than be silently replaced.
- UTF-8 with replacement — substitute invalid sequences.
- Caller-provided encoding — require an encoding argument.

### 7. Should links be followed or resolved?
- **Preserve authored destination — selected.** Keep label and destination as parsed; do not follow links or access the network.
- Resolve local links — resolve relative links against the source file.
- Follow linked Markdown — traverse and parse linked documents.

## Parsed result and domain structure

### 8. What structure should one parsed file return?
- **Sections with ordered blocks — selected.** Include title and sections; retain ordered paragraphs, lists, and code blocks.
- Full Markdown AST — expose a syntax tree with supported Markdown nodes and nesting.
- Normalized text — title and cleaned text without block types.

### 9. Should heading context preserve the full path?
- **Preserve full path — selected.** Keep ancestor titles available for later chunking and attribution.
- Nearest heading only — retain only the current heading.
- No sections — return content without heading context.

### 10. How should the H1 title be represented?
- **First H1 as plain-text title — selected.** Use it as document title and root of heading paths.
- Filename — derive title from the Markdown filename.
- Caller supplies title — require title separately.

### 11. Should section titles/path elements preserve inline markup?
- **Plain-text headings — selected.** Normalize heading labels to readable text; retain inline structure in body content.
- Structured heading nodes — retain inline formatting and links in headings.

### 12. How should section boundaries work?
- **A heading owns following content — selected.** It contains subsequent blocks and nested sections until a same-or-higher-level heading; H1 is title, not a content section.
- Every heading is a block — keep a flat block stream.
- H2-only sections — deeper headings remain blocks within H2.

### 13. Where should content between H1 and first H2 go?
- **Document introduction — selected.** Store it as ordered document-level blocks before sections.
- First section — attach it to the first H2.
- Reject it — require content to follow a section heading.

### 14. How should content and nested sections be ordered?
- **One ordered child stream — selected.** Each section has one ordered sequence of blocks and child sections, preserving their interleaving in source.
- Separate block and section lists — ordering between them is not represented.

### 15. What should happen to empty sections?
- **Preserve empty section — selected.** Keep it in order with no content blocks and its heading range.
- Reject empty sections.
- Omit empty sections.

### 16. Are duplicate section titles allowed?
- **Allow distinct sections — selected.** Keep repeated titles in source order; path and source ranges distinguish occurrences.
- Reject duplicates.
- Add generated IDs.

### 17. What parser-owned Python model should represent output?
- **Typed dataclasses — selected.** Keep parsed-result types separate from SQLModel database entities and API schemas.
- Pydantic models — validate and serialize parsed results with Pydantic.
- Raw parser tokens — return the selected library's tokens directly.

## Markdown constructs and fidelity

### 18. How should fenced code and other code blocks be handled?
- **Preserve as code blocks — selected.** Keep code identifiable as code, not flattened into prose.
- Flatten to text — include code but discard its block/language distinction.
- Exclude code blocks.

### 19. What should blocks expose beyond content and type?
- Minimal typed blocks — paragraph/list/code types and code language only.
- **Include list details — selected, with the user's added requirement to preserve inline formatting and tables.** The user specifically chose option 2 and added those preservation requirements; later questions refined them below.
- Full Markdown semantics — retain all supported Markdown details.

### 20. What list details should be retained?
- **Order, nesting, item boundaries — selected.** Preserve ordered/unordered state, nested lists, separate items, and item inline formatting.
- Order and items only — flatten nested lists.
- List text only — one text block.

### 21. Should ordered lists retain their explicit starting number?
- **Preserve start number — selected.** Keep the starting value in addition to item order and nesting.
- Use implicit numbering — treat every ordered list as starting at 1.

### 22. How should tables be represented?
- **Header and rows of cells — selected.** Keep header and body rows as cell arrays; parse inline formatting in cells and ignore visual alignment markers.
- Preserve alignment too — additionally store column alignment.
- Raw table Markdown — keep the entire source table.

### 23. Which inline syntax should be preserved structurally?
- **Common inline syntax — selected.** Preserve emphasis/strong, code spans, links with destinations, strikethrough, and text as text.
- All parser-supported inline nodes.
- Raw inline Markdown — keep inline source unchanged.

### 24. Should images be preserved?
- **Yes, preserve image nodes — selected.** Retain alt text and destination as inline structure.
- Flatten to alt text.
- Exclude images.

### 25. What should happen to deeper headings (H3+)?
- **Preserve nested sections — selected.** Allow deeper levels and retain full heading paths.
- Reject deeper headings.
- Flatten under current H2.

### 26. Which dialect defines supported syntax?
- **GitHub Flavored Markdown — selected.** Use GFM semantics for tables, strikethrough, task lists, and supported extensions.
- CommonMark plus tables.
- No fixed dialect — support observed handbook syntax without naming a dialect.

### 27. What GFM conformance level is required?
- **Named construct support — selected.** Support the requested named constructs, without promising complete GitHub parity or every edge case.
- Exact GitHub behavior — match current GFM parsing including edge cases and autolinks.
- CommonMark plus handbook cases — defer other GFM features.

### 28. Should task-list state be retained?
- **Preserve checkbox state — selected.** Represent checked and unchecked task items distinctly.
- Treat as ordinary list text.
- Reject task lists.

### 29. Should blockquotes and thematic breaks be supported?
- **Yes, preserve both — selected.** Represent typed blocks and nested content where applicable.
- No, handbook subset only.
- Blockquotes only.

### 30. How should raw HTML be handled?
- **Preserve only — selected.** Keep raw HTML as opaque source; do not render, filter, or sanitize it in the parser. Sanitization, if needed, belongs at a later rendering boundary.
- Sanitize during parsing.
- Reject HTML.

### 31. What happens to syntax outside GFM, such as footnotes or math?
- Preserve unrecognized source opaquely.
- Reject unsupported syntax.
- **Flatten to text — selected.** Retain readable text but discard unsupported syntax semantics.

### 32. Should Markdown links be resolved or fetched?
- **Preserve authored destination — selected.** Keep the parsed link target as written; do not resolve or follow it.
- Resolve local links.
- Follow linked Markdown.

## Source ranges, validation, and dependency

### 33. Should parser output retain source line ranges?
- **Yes, retain line ranges — selected.** Support later citations, diagnostics, and source traceability.
- No — keep parsed structure independent of positions.
- Only document path — track file, not block positions.

### 34. Which lines should a block range cover?
- **Include source syntax — selected.** Use inclusive ranges spanning original Markdown syntax, such as fences, list markers, and table delimiters.
- Rendered content only — exclude syntax lines where practical.
- Sections only — omit per-block ranges.

### 35. What line numbering convention should be used?
- **1-based inclusive — selected.** Use human/editor line numbers and include both endpoints.
- 0-based half-open — use zero-based start and exclusive end.

### 36. How precise must source ranges be for nested content?
- Ranges on every parsed block — require accurate ranges on every nested block node.
- **Top-level block ranges — selected.** Require section and top-level block ranges; nested child blocks may inherit their parent's range.
- Ranges only on sections.

### 37. Should sections have their own ranges?
- **Yes, inclusive section spans — selected.** Span heading through content, including descendants, up to but not including the next same-or-higher-level heading; blocks also retain their own ranges.
- Heading line only.
- No section ranges.

### 38. What heading structure is valid?
- **Require exactly one H1 — selected.** Reject missing or multiple H1s; H1 supplies title.
- Allow missing H1 and fall back to filename.
- Support general heading structure and let callers decide title semantics.

### 39. Must a document contain an H2?
- **Require an H2 — selected.** Require at least one section in addition to the H1 title.
- H1 plus introduction is valid.

### 40. What should happen to content before H1?
- **Reject pre-title content — selected.** Require H1 to be the first meaningful Markdown block.
- Retain as leading blocks.
- Ignore it.

### 41. What input errors should raise a clear parse error?
- **Empty or invalid title structure — selected.** Reject whitespace-only input and missing/multiple H1s; let the parser tolerate recoverable Markdown syntax.
- Strict Markdown validation — reject malformed Markdown too.
- Never reject syntax — best-effort parse with diagnostics.

### 42. Should the parser compute `content_hash`?
- **Separate hashing — selected.** Parser returns structure; ingestion/persistence layer hashes original bytes/text.
- Parser calculates SHA-256.
- No hash responsibility — defer hashing ownership.

### 43. Which mature Markdown parser should be used?
- Mature library — use a suitable parser after verifying GFM, node fidelity, and source positions.
- Custom parser — implement the handbook subset directly.
- **Final selection: markdown-it-py.** The grill first chose “mature library,” then, after reviewing library capability research, explicitly selected markdown-it-py. The deciding fit was its block line maps and traversable syntax tree; GFM is configured for the named constructs, not exact GitHub parity.
- Marko and Mistune were also discussed in the capability comparison; neither was selected.

## Final scope confirmation

### 44. Proceed to planning or implementation?
- **Yes — plan next — selected.** The user confirmed the summarized scope and chose a concrete implementation plan before coding.
- Yes — implement — begin parser implementation immediately.
- No — revise — clarify requirements first.

The confirmed scope is a handbook-only, one-document parser in `backend/app/ingestion`, returning typed dataclasses with no DB writes, chunking, hashing, or embeddings. It accepts Markdown text or strict UTF-8 file paths, with optional source path for text input; requires exactly one H1 and at least one H2; preserves nested sections and ordered typed content, specified inline/block syntax, and source provenance; and targets named GFM constructs using markdown-it-py without claiming exact GitHub parity.
