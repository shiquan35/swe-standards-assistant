# Knowledge Ingestion

This context covers the engineering handbook as source material for knowledge retrieval.

## Language

**Handbook document**:
A single Markdown source file in the engineering handbook, with a document title and organized content.
_Avoid_: Knowledge document when referring to the source file itself.

**Knowledge document**:
A persisted record representing one handbook document and its source identity; it may have multiple associated chunks.
_Avoid_: Handbook document when referring specifically to the database record.

**Section**:
A titled part of a handbook document, with its own content and potentially nested titled parts.
_Avoid_: Chunk; a section is source organization, not a retrieval-sized unit.

**Content block**:
An ordered unit of content within a document or section, such as prose, a list, code, or a table.
_Avoid_: Chunk; a block is not necessarily the unit persisted or embedded for retrieval.

**Chunk**:
A persisted content unit associated with one knowledge document; unlike a section, it is not the source document's heading-defined organization.
_Avoid_: Section when referring to a persisted content unit.

**Chunk candidate**:
A transient, not-yet-persisted content unit produced by chunking a handbook document.
_Avoid_: Chunk when referring specifically to output that has not been persisted.

**Chunking strategy**:
A method for dividing a handbook document into persisted chunks, such as fixed, fixed-overlap, or heading-aware chunking.
_Avoid_: Retrieval strategy; chunking strategy describes source segmentation, not how retrieved chunks are ranked.

**Heading path**:
The ordered hierarchy of plain-text titles from the document title through the containing section titles.
_Avoid_: Heading when the full ancestry is intended; heading may mean only the nearest title.

**Evaluation case**:
A question and its curated labels used to assess retrieval behavior; the labels describe known support, not every result that could be useful.
_Avoid_: Ground-truth case when the labels are intentionally incomplete.

**Expected evidence**:
A handbook statement known to support an evaluation case; the set may be incomplete and its absence from retrieved content does not prove a result irrelevant.
_Avoid_: Complete answer key.

**Evidence coverage**:
The portion of an evaluation case's expected evidence found in retrieved content; it is a retrieval diagnostic, not a complete measure of relevance or answer quality.
_Avoid_: Overall retrieval quality when only curated evidence labels are available.

**Manual relevance judgment**:
A human assessment of whether a retrieved result is useful for answering its evaluation case, including useful results not represented by the curated evidence labels.
_Avoid_: Evidence match; these are distinct assessments.
