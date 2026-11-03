"""Deterministic, transient chunking over frozen canonical character intervals.

Every fit is an independent encoding of the complete emitted string. Searches
are descending and exhaustive, not binary: even an injected tokenizer need not
have monotone prefix lengths. The bounded count cache belongs to one operation;
neither source strings nor tokenizer results are retained globally.
"""

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar

from app.core.logger import app_logger
from app.ingestion.chunk_models import (
    BodyRun,
    ChunkCandidate,
    ChunkingConfig,
    ChunkingError,
    ChunkPart,
    ChunkStrategy,
    ContextKind,
    SerializedBlock,
    SerializedMarkdown,
    Tokenizer,
)
from app.ingestion.markdown_models import ParsedDocument, Section, SourceRange
from app.ingestion.markdown_serializer import _escape, serialize_markdown
from app.ingestion.tokenizer import TiktokenTokenizer, validate_unicode

_STRATEGIES = ("fixed", "fixed_overlap", "heading_aware")


def _configuration(
    strategy: ChunkStrategy, config: ChunkingConfig | None
) -> ChunkingConfig:
    if strategy not in _STRATEGIES:
        raise ValueError("unknown_chunk_strategy")
    try:
        # Revalidate mutable configuration objects at the public boundary.
        result = (
            ChunkingConfig(config.max_tokens, config.overlap_tokens)
            if config is not None
            else ChunkingConfig(500, 0 if strategy == "fixed" else 100)
        )
        if strategy == "fixed" and result.overlap_tokens:
            raise ValueError("fixed_requires_zero_overlap")
    except ValueError as error:
        app_logger.bind(
            max_tokens=(
                config.max_tokens
                if config is not None and type(config.max_tokens) is int
                else None
            ),
            overlap_tokens=(
                config.overlap_tokens
                if config is not None and type(config.overlap_tokens) is int
                else None
            ),
            reason_code=str(error),
        ).warning("chunk_invalid_config")
        raise
    return result


class _Counts:
    """Bound both retained strings and their total size during an operation."""

    def __init__(self, tokenizer: Tokenizer) -> None:
        self.tokenizer = tokenizer
        self.cache: OrderedDict[str, int] = OrderedDict()
        self.characters = 0

    def __call__(self, text: str) -> int:
        if text in self.cache:
            self.cache.move_to_end(text)
            return self.cache[text]
        result = len(self.tokenizer.encode(text))
        if len(text) <= 262_144:
            self.cache[text] = result
            self.characters += len(text)
            while len(self.cache) > 1024 or self.characters > 262_144:
                key, _ = self.cache.popitem(last=False)
                self.characters -= len(key)
        return result


def _eligible(
    serialized: SerializedMarkdown, strategy: ChunkStrategy
) -> list[tuple[int, int, BodyRun | None]]:
    if strategy == "heading_aware":
        return [
            (run.start, run.end, run)
            for run in serialized.runs
            if serialized.text[run.start : run.end].strip()
        ]
    return [(0, len(serialized.text), None)] if serialized.text.strip() else []


def _breadcrumb(run: BodyRun) -> str:
    return "\n".join(
        "#" * level + " " + _escape(heading)
        for heading, level in zip(run.heading_path, run.heading_levels, strict=True)
    )


def _continuation(run: BodyRun, start: int) -> SerializedBlock | None:
    return next(
        (
            block
            for block in run.blocks
            if block.table_header is not None and block.start < start < block.end
        ),
        None,
    )


def _contexts(
    run: BodyRun | None, start: int, *, prefix: bool, table: bool
) -> list[tuple[str, ContextKind]]:
    result: list[tuple[str, ContextKind]] = []
    if run is None:
        return result
    if prefix:
        result.extend(
            [(_breadcrumb(run), "heading_breadcrumb"), ("\n\n", "markdown_wrapper")]
        )
    block = _continuation(run, start) if table else None
    if block is not None and block.table_header:
        result.extend(
            [(block.table_header, "table_header"), ("\n", "markdown_wrapper")]
        )
    return result


def _parts(
    contexts: list[tuple[str, ContextKind]], start: int, cursor: int, end: int
) -> list[ChunkPart]:
    result: list[ChunkPart] = []
    offset = 0
    for text, kind in contexts:
        result.append(
            ChunkPart(offset, offset + len(text), "context", context_kind=kind)
        )
        offset += len(text)
    if start < cursor:
        result.append(
            ChunkPart(offset, offset + cursor - start, "overlap", start, cursor)
        )
        offset += cursor - start
    result.append(ChunkPart(offset, offset + end - cursor, "source", cursor, end))
    return result


def _heading_references(serialized: SerializedMarkdown, run: BodyRun) -> list[int]:
    """Find actual outline segments, not guessed source lines for the title."""
    references: list[int] = []
    for depth, (heading, level) in enumerate(
        zip(run.heading_path, run.heading_levels, strict=True), start=1
    ):
        matching = [
            index
            for index, segment in enumerate(serialized.segments)
            if segment.end <= run.start
            and segment.heading_path == run.heading_path[:depth]
            and serialized.text[segment.start : segment.end]
            == "#" * level + " " + _escape(heading)
            and not any(
                body.start <= segment.start < body.end for body in serialized.runs
            )
        ]
        if matching:
            references.append(matching[-1])
    return references


def _metadata(
    serialized: SerializedMarkdown,
    parts: list[ChunkPart],
    run: BodyRun | None,
) -> tuple[list[list[str]], list[SourceRange]]:
    intervals = [
        (part.canonical_start, part.canonical_end)
        for part in parts
        if part.role != "context"
        and part.canonical_start is not None
        and part.canonical_end is not None
    ]
    contexts = {part.context_kind for part in parts if part.role == "context"}
    references: set[int] = set()
    if run is not None:
        if "heading_breadcrumb" in contexts:
            references.update(_heading_references(serialized, run))
        if "table_header" in contexts and intervals:
            block = _continuation(run, intervals[0][0])
            if block is not None and block.table_header:
                intervals_for_header = (
                    block.start,
                    block.start + len(block.table_header),
                )
                references.update(
                    index
                    for index, segment in enumerate(serialized.segments)
                    if segment.start < intervals_for_header[1]
                    and segment.end > intervals_for_header[0]
                )
    paths: list[list[str]] = []
    spans: list[SourceRange] = []
    for index, segment in enumerate(serialized.segments):
        mapped = any(
            segment.start < end and segment.end > start for start, end in intervals
        )
        if mapped and segment.heading_path not in paths:
            paths.append(list(segment.heading_path))
        if (mapped or index in references) and segment.source_range is not None:
            source = segment.source_range
            if source not in spans:
                spans.append(SourceRange(source.start_line, source.end_line))
    return paths, spans


def _suffixes(
    text: str,
    cursor: int,
    previous_start: int,
    starts: Iterable[int],
    config: ChunkingConfig,
    count: _Counts,
) -> list[int]:
    ranked = [
        (count(text[start:cursor]), start)
        for start in starts
        if previous_start <= start < cursor
    ]
    ranked = [item for item in ranked if item[0] <= config.overlap_tokens]
    ranked.sort(key=lambda item: (-item[0], item[1]))
    # Zero overlap is always available, even for an exotic injected tokenizer.
    return [start for _, start in ranked] + [cursor]


@dataclass
class _Choice:
    start: int
    end: int
    contexts: list[tuple[str, ContextKind]]
    prefix_omitted: bool = False
    fine: bool = False


class _Engine:
    strategy: ChunkStrategy

    def __init__(
        self,
        serialized: SerializedMarkdown,
        strategy: ChunkStrategy,
        config: ChunkingConfig,
        count: _Counts,
    ) -> None:
        self.serialized = serialized
        self.strategy = strategy
        self.config = config
        self.count = count

    def _fit(
        self,
        cursor: int,
        ends: Iterable[int],
        starts: list[int],
        run: BodyRun | None,
        *,
        prefix: bool,
        table: bool,
        fine: bool = False,
    ) -> _Choice | None:
        # All callers provide reusable ranges/lists, not one-shot generators.
        for start in starts:
            contexts = _contexts(run, start, prefix=prefix, table=table)
            context = "".join(text for text, _ in contexts)
            for end in ends:
                if (
                    end > cursor
                    and self.count(context + self.serialized.text[start:end])
                    <= self.config.max_tokens
                ):
                    return _Choice(
                        start, end, contexts, run is not None and not prefix, fine
                    )
        return None

    def _heading_choice(self, cursor: int, starts: list[int], run: BodyRun) -> _Choice:
        block = next(block for block in run.blocks if block.end > cursor)
        block_ends = sorted(
            {item.end for item in run.blocks if item.end > cursor}, reverse=True
        )
        fine_ends = sorted(
            {end for end in block.boundaries if end > cursor}, reverse=True
        )
        unit_end = min(fine_ends, default=block.end)
        tiers = [
            (block_ends, False),
            (fine_ends, True),
            (range(unit_end, cursor, -1), True),
        ]
        # Reduce overlap before splitting the next intact block/unit. Repeated
        # headers yield only after every advancing normal rendering was tried.
        for ends, fine in tiers:
            choice = self._fit(
                cursor, ends, starts, run, prefix=True, table=True, fine=fine
            )
            if choice is not None:
                return choice
        # Nonmonotone encodings can fit a later end even if no prefix of the
        # first unit fits. Exhaust the remaining run before omitting context.
        choice = self._fit(
            cursor,
            range(run.end, cursor, -1),
            starts,
            run,
            prefix=True,
            table=True,
            fine=True,
        )
        if choice is not None:
            return choice
        for prefix in (True, False):
            for ends, fine in [*tiers, (range(run.end, cursor, -1), True)]:
                choice = self._fit(
                    cursor,
                    ends,
                    [cursor],
                    run,
                    prefix=prefix,
                    table=False,
                    fine=fine,
                )
                if choice is not None:
                    return choice
        raise ChunkingError("token_budget_unrepresentable")

    def build(self, source_path: str | None) -> list[ChunkCandidate]:
        candidates: list[ChunkCandidate] = []
        text = self.serialized.text
        for begin, end, run in _eligible(self.serialized, self.strategy):
            cursor = previous_start = begin
            natural = {begin}
            if run is not None:
                natural.update(block.start for block in run.blocks)
                natural.update(block.end for block in run.blocks)
            fragment = False
            while cursor < end:
                starts = [cursor]
                if cursor > begin and self.config.overlap_tokens:
                    eligible_starts = (
                        range(previous_start, cursor)
                        if run is None or fragment
                        else natural
                    )
                    starts = _suffixes(
                        text,
                        cursor,
                        previous_start,
                        eligible_starts,
                        self.config,
                        self.count,
                    )
                if run is None:
                    choice = self._fit(
                        cursor,
                        range(end, cursor, -1),
                        starts,
                        None,
                        prefix=False,
                        table=False,
                    )
                    if choice is None:
                        raise ChunkingError("token_budget_unrepresentable")
                else:
                    choice = self._heading_choice(cursor, starts, run)
                    if choice.fine:
                        for block in run.blocks:
                            if block.start < choice.end and block.end > cursor:
                                natural.update(block.boundaries)
                    fragment = choice.end not in natural
                parts = _parts(choice.contexts, choice.start, cursor, choice.end)
                content = (
                    "".join(value for value, _ in choice.contexts)
                    + text[choice.start : choice.end]
                )
                paths, spans = _metadata(self.serialized, parts, run)
                candidates.append(
                    ChunkCandidate(
                        ordinal=len(candidates),
                        strategy=self.strategy,
                        content=content,
                        token_count=self.count(content),
                        source_path=source_path,
                        heading_paths=paths,
                        source_spans=spans,
                        parts=parts,
                        actual_overlap_tokens=(
                            self.count(text[choice.start : cursor])
                            if choice.start < cursor
                            else 0
                        ),
                        heading_prefix_omitted=choice.prefix_omitted,
                    )
                )
                previous_start, cursor = choice.start, choice.end
        return candidates


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ChunkingError("invariant_" + reason)


def _validate(
    serialized: SerializedMarkdown,
    candidates: list[ChunkCandidate],
    strategy: ChunkStrategy,
    config: ChunkingConfig,
    count: _Counts,
) -> None:
    validate_unicode(serialized.text)
    streams = _eligible(serialized, strategy)
    stream_index = 0
    cursor = streams[0][0] if streams else 0
    previous_start = cursor
    source_path = candidates[0].source_path if candidates else None
    for ordinal, candidate in enumerate(candidates):
        _require(stream_index < len(streams), "unexpected_candidate")
        begin, limit, run = streams[stream_index]
        validate_unicode(candidate.content)
        _require(candidate.ordinal == ordinal, "ordinal")
        _require(candidate.strategy == strategy, "strategy")
        _require(candidate.source_path == source_path, "source_path")
        _require(candidate.token_count == count(candidate.content), "token_count")
        _require(candidate.token_count <= config.max_tokens, "token_budget")
        _require(bool(candidate.parts), "missing_parts")
        output_cursor = 0
        mapped: list[ChunkPart] = []
        source: list[ChunkPart] = []
        overlap: list[ChunkPart] = []
        seen_source = False
        for part in candidate.parts:
            _require(
                part.output_start == output_cursor
                and part.output_start < part.output_end <= len(candidate.content),
                "output_partition",
            )
            output_cursor = part.output_end
            if part.role == "context":
                _require(
                    part.canonical_start is None and part.canonical_end is None,
                    "context_coverage",
                )
                _require(
                    run is not None
                    and not mapped
                    and part.context_kind
                    in ("heading_breadcrumb", "table_header", "markdown_wrapper"),
                    "context_kind_or_order",
                )
                continue
            _require(part.role in ("source", "overlap"), "part_role")
            _require(part.context_kind is None, "mapped_context_kind")
            start, end = part.canonical_start, part.canonical_end
            _require(start is not None and end is not None, "missing_offsets")
            # Narrow explicitly after the content-free invariant check.
            assert start is not None and end is not None
            _require(begin <= start < end <= limit, "canonical_interval")
            _require(
                candidate.content[part.output_start : part.output_end]
                == serialized.text[start:end],
                "role_text",
            )
            if mapped:
                _require(mapped[-1].canonical_end == start, "mapped_order")
            mapped.append(part)
            if part.role == "source":
                seen_source = True
                _require(start == cursor, "source_partition")
                cursor = end
                source.append(part)
            else:
                _require(not seen_source, "overlap_order")
                overlap.append(part)
        _require(output_cursor == len(candidate.content), "output_partition")
        _require(bool(source), "no_progress")
        first_source = source[0].canonical_start
        assert first_source is not None
        start = mapped[0].canonical_start
        assert start is not None
        if overlap:
            _require(
                previous_start <= start < first_source
                and overlap[-1].canonical_end == first_source
                and first_source > begin,
                "overlap_suffix",
            )
            actual = count(serialized.text[start:first_source])
        else:
            _require(start == first_source, "source_start")
            actual = 0
        _require(
            candidate.actual_overlap_tokens == actual
            and actual <= config.overlap_tokens
            and (strategy != "fixed" or not overlap),
            "actual_overlap",
        )
        prefix = run is not None and not candidate.heading_prefix_omitted
        has_table = any(part.context_kind == "table_header" for part in candidate.parts)
        _require(run is not None or not candidate.heading_prefix_omitted, "prefix_flag")
        contexts = _contexts(run, start, prefix=prefix, table=has_table)
        # Check generated text, including explicit context separators, against
        # the same frozen canonical header and escaped outline representation.
        expected = _parts(contexts, start, first_source, cursor)
        _require(candidate.parts == expected, "rendered_parts")
        _require(
            candidate.content
            == "".join(value for value, _ in contexts) + serialized.text[start:cursor],
            "rendered_content",
        )
        if run is not None and candidate.heading_prefix_omitted:
            breadcrumb = _breadcrumb(run) + "\n\n"
            _require(
                not any(
                    count(breadcrumb + serialized.text[first_source:end])
                    <= config.max_tokens
                    for end in range(limit, first_source, -1)
                ),
                "unnecessary_prefix_omission",
            )
        paths, spans = _metadata(serialized, candidate.parts, run)
        _require(candidate.heading_paths == paths, "heading_paths")
        _require(candidate.source_spans == spans, "source_spans")
        if run is not None:
            _require(paths == [run.heading_path], "mixed_heading_paths")
        previous_start = start
        if cursor == limit:
            stream_index += 1
            if stream_index < len(streams):
                cursor = previous_start = streams[stream_index][0]
    _require(stream_index == len(streams), "incomplete_coverage")


def validate_chunks(
    serialized: SerializedMarkdown,
    candidates: list[ChunkCandidate],
    strategy: ChunkStrategy,
    config: ChunkingConfig,
    tokenizer: Tokenizer,
) -> None:
    """Raise ChunkingError for an output invariant failure; never text-dedupe.

    The frozen serializer map is the authority for coverage and provenance.
    Source paths can only be checked for consistency here: SerializedMarkdown
    deliberately contains no document path. The producer copies it from the AST.
    """
    checked = _configuration(strategy, config)
    try:
        _validate(serialized, candidates, strategy, checked, _Counts(tokenizer))
    except ChunkingError as error:
        app_logger.bind(
            strategy=strategy,
            error_type=type(error).__name__,
            reason_code=error.reason_code,
        ).error("chunk_validation_error")
        raise


def _structure(document: ParsedDocument) -> tuple[int, list[str]]:
    section_count = 0
    block_types: set[str] = set()

    def visit(children: Iterable[object]) -> None:
        nonlocal section_count
        for child in children:
            if isinstance(child, Section):
                section_count += 1
                visit(child.children)
            else:
                block_types.add(getattr(child, "kind", type(child).__name__))

    visit(document.introduction)
    visit(document.sections)
    return section_count, sorted(block_types)


def chunk_document(
    document: ParsedDocument,
    strategy: ChunkStrategy = "heading_aware",
    config: ChunkingConfig | None = None,
    tokenizer: Tokenizer | None = None,
) -> list[ChunkCandidate]:
    """Serialize once, chunk atomically, and validate before returning results."""
    checked = _configuration(strategy, config)
    section_count, block_types = _structure(document)
    app_logger.bind(
        strategy=strategy,
        max_tokens=checked.max_tokens,
        overlap_tokens=checked.overlap_tokens,
        section_count=section_count,
        block_types=block_types,
    ).debug("chunk_entry")
    try:
        serialized = serialize_markdown(document)
        # Empty ASTs/runs need neither tokenizer initialization nor a vocabulary
        # cache lookup. Unicode was still validated by the serializer.
        if not _eligible(serialized, strategy):
            candidates: list[ChunkCandidate] = []
        else:
            count = _Counts(tokenizer if tokenizer is not None else TiktokenTokenizer())
            candidates = _Engine(serialized, strategy, checked, count).build(
                document.source_path
            )
            _validate(serialized, candidates, strategy, checked, count)
    except Exception as error:
        app_logger.bind(
            strategy=strategy,
            error_type=type(error).__name__,
            reason_code=(
                error.reason_code
                if isinstance(error, ChunkingError)
                else "chunk_operation_failed"
            ),
        ).error("chunk_error")
        raise
    app_logger.bind(
        strategy=strategy,
        token_counts=[candidate.token_count for candidate in candidates],
        source_spans=[
            [[span.start_line, span.end_line] for span in candidate.source_spans]
            for candidate in candidates
        ],
        heading_depths=[
            [len(path) for path in candidate.heading_paths] for candidate in candidates
        ],
        diagnostics=[
            {
                "ordinal": candidate.ordinal,
                "actual_overlap_tokens": candidate.actual_overlap_tokens,
                "heading_prefix_omitted": candidate.heading_prefix_omitted,
            }
            for candidate in candidates
        ],
    ).debug("chunk_success")
    return candidates


class _Chunker:
    strategy: ClassVar[ChunkStrategy]

    def __init__(
        self, config: ChunkingConfig | None = None, tokenizer: Tokenizer | None = None
    ) -> None:
        self.config = _configuration(self.strategy, config)
        self.tokenizer = tokenizer

    def chunk(
        self,
        document: ParsedDocument,
        config: ChunkingConfig | None = None,
        tokenizer: Tokenizer | None = None,
    ) -> list[ChunkCandidate]:
        return chunk_document(
            document,
            self.strategy,
            self.config if config is None else config,
            self.tokenizer if tokenizer is None else tokenizer,
        )


class FixedSizeChunker(_Chunker):
    """Whole-document windows, default 500 tokens; nonzero overlap is invalid."""

    strategy: ClassVar[ChunkStrategy] = "fixed"


class FixedOverlapChunker(_Chunker):
    """Whole-document windows with ranked character suffixes, default 500/100."""

    strategy: ClassVar[ChunkStrategy] = "fixed_overlap"


class HeadingAwareChunker(_Chunker):
    """Contiguous body runs, natural packing and generated context, default 500/100."""

    strategy: ClassVar[ChunkStrategy] = "heading_aware"
