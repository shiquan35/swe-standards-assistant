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

**Heading path**:
The ordered hierarchy of plain-text titles from the document title through the containing section titles.
_Avoid_: Heading when the full ancestry is intended; heading may mean only the nearest title.
