"""Transient chunking contracts; offsets are half-open Python character offsets."""

from dataclasses import dataclass, field
from typing import Literal, Protocol

from app.ingestion.markdown_models import Block, ParsedDocument, SourceRange

type ChunkStrategy = Literal["fixed", "fixed_overlap", "heading_aware"]
type PartRole = Literal["source", "overlap", "context"]
type ContextKind = Literal["heading_breadcrumb", "table_header", "markdown_wrapper"]


class ChunkingError(ValueError):
    """Content-free failure code safe to expose in diagnostics."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass
class ChunkingConfig:
    max_tokens: int = 500
    overlap_tokens: int = 100

    def __post_init__(self) -> None:
        if type(self.max_tokens) is not int or self.max_tokens <= 0:
            raise ValueError("max_tokens_must_be_positive_integer")
        if type(self.overlap_tokens) is not int or self.overlap_tokens < 0:
            raise ValueError("overlap_tokens_must_be_nonnegative_integer")
        if self.overlap_tokens >= self.max_tokens:
            raise ValueError("overlap_not_less_than_max")


@dataclass
class ChunkPart:
    output_start: int
    output_end: int
    role: PartRole
    canonical_start: int | None = None
    canonical_end: int | None = None
    context_kind: ContextKind | None = None


@dataclass
class ChunkCandidate:
    ordinal: int
    strategy: ChunkStrategy
    content: str
    token_count: int
    source_path: str | None = None
    heading_paths: list[list[str]] = field(default_factory=list)
    source_spans: list[SourceRange] = field(default_factory=list)
    parts: list[ChunkPart] = field(default_factory=list)
    actual_overlap_tokens: int = 0
    heading_prefix_omitted: bool = False


@dataclass
class SerializedSegment:
    """An emitted interval; separators have no invented source range."""

    start: int
    end: int
    heading_path: list[str]
    source_range: SourceRange | None


@dataclass
class SerializedBlock:
    """Direct block and absolute natural-unit ends, including the block end.

    Boundaries partition list items, table header/rows, code lines, or quote
    children. Inter-unit separators belong to the preceding unit. Other blocks
    are single units. The AST reference is read-only; its ranges remain coarse.
    """

    start: int
    end: int
    block: Block
    boundaries: list[int]
    table_header: str | None = None


@dataclass
class BodyRun:
    """One contiguous direct body, never spanning an intervening subsection.

    Includes separators between its blocks, but not surrounding outline text.
    Heading levels come from traversal, so skipped outline levels are retained.
    """

    start: int
    end: int
    heading_path: list[str]
    heading_levels: list[int]
    blocks: list[SerializedBlock]


@dataclass
class SerializedMarkdown:
    text: str
    segments: list[SerializedSegment]
    runs: list[BodyRun]


class Tokenizer(Protocol):
    def encode(self, text: str) -> list[int]: ...


class Chunker(Protocol):
    def chunk(
        self, document: ParsedDocument, config: ChunkingConfig, tokenizer: Tokenizer
    ) -> list[ChunkCandidate]: ...
