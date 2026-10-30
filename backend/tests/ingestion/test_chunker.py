"""Output contracts for phase 2 chunking; no database or embedding services."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from socket import socket
from typing import cast
from unittest.mock import Mock

import pytest
import tiktoken

from app.ingestion import (
    ChunkCandidate,
    Chunker,
    ChunkingConfig,
    ChunkingError,
    ChunkStrategy,
    FixedOverlapChunker,
    FixedSizeChunker,
    HeadingAwareChunker,
    MarkdownParseError,
    Paragraph,
    ParsedDocument,
    RawHTMLBlock,
    Section,
    SourceRange,
    Text,
    TiktokenTokenizer,
    Tokenizer,
    chunk_document,
    parse_markdown,
    parse_markdown_file,
    serialize_markdown,
    validate_chunks,
)

STRATEGIES: tuple[ChunkStrategy, ...] = ("fixed", "fixed_overlap", "heading_aware")
HANDBOOK = Path(__file__).resolve().parents[2] / "knowledge_base/engineering-handbook"
TOPICS = sorted(path for path in HANDBOOK.glob("*.md") if path.name != "README.md")


class Characters:
    """A transparent code-point tokenizer for exact boundary expectations."""

    def encode(self, text: str) -> list[int]:
        return list(range(len(text)))


class Nonmonotone:
    """Reject every short prefix while accepting a later complete endpoint."""

    def encode(self, text: str) -> list[int]:
        return [0] if text.endswith("MAGIC") else list(range(2 * len(text)))


def document_with_body(text: str, title: str = "D") -> ParsedDocument:
    return ParsedDocument(
        title, "private/topic.md", [Paragraph([Text(text)], SourceRange(3, 5))], []
    )


def assert_output(
    document: ParsedDocument,
    candidates: list[ChunkCandidate],
    strategy: ChunkStrategy,
    config: ChunkingConfig,
    tokenizer: Tokenizer,
) -> None:
    """Independently prove offset partitions, progress, counts and provenance.

    The producer's validator is checked too, but is not the test oracle. In
    particular, repeated prose cannot mask missing or duplicated intervals.
    """
    frozen = serialize_markdown(document)
    intervals = (
        [
            (run.start, run.end)
            for run in frozen.runs
            if frozen.text[run.start : run.end].strip()
        ]
        if strategy == "heading_aware"
        else ([(0, len(frozen.text))] if frozen.text.strip() else [])
    )
    source_intervals: list[tuple[int, int]] = []
    source_strings: list[str] = []
    stream_index = 0
    cursor = intervals[0][0] if intervals else 0
    previous_start = cursor
    for ordinal, candidate in enumerate(candidates):
        assert candidate.ordinal == ordinal
        assert candidate.strategy == strategy
        assert candidate.source_path == document.source_path
        assert candidate.token_count == len(tokenizer.encode(candidate.content))
        assert 0 < candidate.token_count <= config.max_tokens
        assert "\ufffd" not in candidate.content
        candidate.content.encode("utf-8", errors="strict")
        begin, end = intervals[stream_index]
        output_cursor = 0
        mapped_start: int | None = None
        overlap_text = ""
        new_text = ""
        first_source = cursor
        mapped_intervals: list[tuple[int, int]] = []
        for part in candidate.parts:
            assert part.output_start == output_cursor
            assert part.output_end > part.output_start
            value = candidate.content[part.output_start : part.output_end]
            output_cursor = part.output_end
            if part.role == "context":
                assert strategy == "heading_aware"
                assert part.canonical_start is part.canonical_end is None
                assert part.context_kind in {
                    "heading_breadcrumb",
                    "table_header",
                    "markdown_wrapper",
                }
                continue
            assert part.context_kind is None
            start, stop = part.canonical_start, part.canonical_end
            assert start is not None and stop is not None
            assert begin <= start < stop <= end
            assert value == frozen.text[start:stop]
            if mapped_intervals:
                assert mapped_intervals[-1][1] == start
            mapped_intervals.append((start, stop))
            if mapped_start is None:
                mapped_start = start
            if part.role == "overlap":
                assert not new_text
                assert previous_start <= start < stop <= first_source
                overlap_text += value
            else:
                assert part.role == "source"
                assert start == cursor
                cursor = stop
                new_text += value
                source_strings.append(value)
                source_intervals.append((start, stop))
        assert output_cursor == len(candidate.content)
        assert new_text  # Every candidate consumes new source, including the tail.
        assert mapped_start is not None
        assert overlap_text == frozen.text[mapped_start:first_source]
        assert candidate.actual_overlap_tokens == (
            len(tokenizer.encode(overlap_text)) if overlap_text else 0
        )
        assert candidate.actual_overlap_tokens <= config.overlap_tokens
        if first_source == begin or strategy == "fixed":
            assert not overlap_text
        paths: list[list[str]] = []
        available_spans = [
            segment.source_range
            for segment in frozen.segments
            if segment.source_range is not None
        ]
        required_spans: list[SourceRange] = []
        for segment in frozen.segments:
            if any(
                segment.start < stop and segment.end > start
                for start, stop in mapped_intervals
            ):
                if segment.heading_path not in paths:
                    paths.append(segment.heading_path)
                if (
                    segment.source_range is not None
                    and segment.source_range not in required_spans
                ):
                    required_spans.append(segment.source_range)
        assert candidate.heading_paths == paths
        assert all(span in available_spans for span in candidate.source_spans)
        assert all(span in candidate.source_spans for span in required_spans)
        assert len(candidate.source_spans) == len(
            {(span.start_line, span.end_line) for span in candidate.source_spans}
        )
        if strategy == "heading_aware":
            run = next(
                run for run in frozen.runs if run.start == begin and run.end == end
            )
            assert paths == [run.heading_path]
            prefixes = [
                part
                for part in candidate.parts
                if part.context_kind == "heading_breadcrumb"
            ]
            assert bool(prefixes) is not candidate.heading_prefix_omitted
            if not candidate.heading_prefix_omitted:
                # The actual emitted canonical outline text also checks escaping.
                outline = []
                for depth, level in enumerate(run.heading_levels, start=1):
                    matching = [
                        frozen.text[segment.start : segment.end]
                        for segment in frozen.segments
                        if segment.end <= run.start
                        and segment.heading_path == run.heading_path[:depth]
                        and frozen.text[segment.start : segment.end].startswith(
                            "#" * level + " "
                        )
                    ]
                    outline.append(matching[-1])
                assert candidate.content.startswith("\n".join(outline) + "\n\n")
        else:
            assert not candidate.heading_prefix_omitted
            assert all(part.role != "context" for part in candidate.parts)
        previous_start = mapped_start
        if cursor == end:
            stream_index += 1
            if stream_index < len(intervals):
                cursor = previous_start = intervals[stream_index][0]
    assert stream_index == len(intervals)
    expected_intervals: list[tuple[int, int]] = []
    for begin, end in intervals:
        expected_intervals.extend(
            (position, position + 1) for position in range(begin, end)
        )
    actual_intervals = [
        (position, position + 1)
        for begin, end in source_intervals
        for position in range(begin, end)
    ]
    assert actual_intervals == expected_intervals
    assert "".join(source_strings) == "".join(
        frozen.text[start:end] for start, end in intervals
    )
    validate_chunks(frozen, candidates, strategy, config, tokenizer)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_defaults_and_protocol(strategy: ChunkStrategy) -> None:
    implementations: dict[ChunkStrategy, Chunker] = {
        "fixed": FixedSizeChunker(),
        "fixed_overlap": FixedOverlapChunker(),
        "heading_aware": HeadingAwareChunker(),
    }
    document = document_with_body("word " * 180)
    config = ChunkingConfig(500, 0 if strategy == "fixed" else 100)
    tokenizer = Characters()
    expected = chunk_document(document, strategy, config, tokenizer)
    assert chunk_document(document, strategy, tokenizer=tokenizer) == expected
    assert implementations[strategy].chunk(document, config, tokenizer) == expected
    assert_output(document, expected, strategy, config, tokenizer)


def test_fixed_rejects_nonzero_overlap_at_every_entry_point() -> None:
    config = ChunkingConfig(20, 1)
    with pytest.raises(ValueError, match="fixed_requires_zero_overlap"):
        FixedSizeChunker(config)
    with pytest.raises(ValueError, match="fixed_requires_zero_overlap"):
        chunk_document(document_with_body("abc"), "fixed", config)
    with pytest.raises(ValueError, match="fixed_requires_zero_overlap"):
        FixedSizeChunker().chunk(document_with_body("abc"), config, Characters())


@pytest.mark.parametrize(
    "maximum,overlap",
    [
        (0, 0),
        (-1, 0),
        (1, -1),
        (2, 2),
        (2, 3),
        (True, 0),
        (4, False),
        (1.5, 0),
        (4, "1"),
        (4, None),
    ],
)
def test_invalid_config(maximum: object, overlap: object) -> None:
    with pytest.raises(ValueError):
        ChunkingConfig(maximum, overlap)  # type: ignore[arg-type]


def test_mutated_config_and_unknown_strategy_are_rejected() -> None:
    config = ChunkingConfig(10, 0)
    config.max_tokens = 0
    with pytest.raises(ValueError):
        chunk_document(document_with_body("abc"), "fixed", config)
    with pytest.raises(ValueError, match="unknown_chunk_strategy"):
        chunk_document(document_with_body("abc"), cast(ChunkStrategy, "unknown"))


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("maximum", [1, 9, 17, 80])
def test_hard_max_determinism_coverage_and_no_ast_mutation(
    strategy: ChunkStrategy, maximum: int
) -> None:
    document = parse_markdown(
        "# D\n\nRepeated paragraph.\n\n## S\n\nRepeated paragraph.\n\nRepeated paragraph.\n\n## S\n\nlast  "
    )
    document.source_path = "sensitive/path.md"
    original = deepcopy(document)
    config = ChunkingConfig(maximum, 0 if strategy == "fixed" else maximum - 1)
    tokenizer = Characters()
    candidates = chunk_document(document, strategy, config, tokenizer)
    assert candidates == chunk_document(document, strategy, config, tokenizer)
    assert document == original
    assert_output(document, candidates, strategy, config, tokenizer)


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("extra", [0, 1])
def test_exact_limit_and_final_tail(strategy: ChunkStrategy, extra: int) -> None:
    document = document_with_body("abcdefghijklmnop")
    config = ChunkingConfig(len(serialize_markdown(document).text) - extra, 0)
    candidates = chunk_document(document, strategy, config, Characters())
    assert len(candidates) == 1 + extra
    assert candidates[0].token_count == config.max_tokens
    assert_output(document, candidates, strategy, config, Characters())


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_empty_ast_heading_tree_and_parser_empty_are_distinct(
    strategy: ChunkStrategy,
) -> None:
    empty = ParsedDocument("D", None, [], [])
    assert chunk_document(empty, strategy) == []
    heading_only = parse_markdown("# D\n\n## Empty\n\n#### Nested")
    candidates = chunk_document(heading_only, strategy)
    assert bool(candidates) is (strategy != "heading_aware")
    assert_output(
        heading_only,
        candidates,
        strategy,
        ChunkingConfig(500, 0 if strategy == "fixed" else 100),
        TiktokenTokenizer(),
    )
    with pytest.raises(MarkdownParseError):
        parse_markdown("")


def test_whitespace_run_empty_but_nonblank_run_retains_every_separator() -> None:
    blank = ParsedDocument("D", None, [RawHTMLBlock(" \n\t ", SourceRange(3, 4))], [])
    assert chunk_document(blank, "heading_aware") == []
    document = ParsedDocument(
        "D", None, [RawHTMLBlock(" \n X \n\t ", SourceRange(3, 5))], []
    )
    for strategy in STRATEGIES:
        config = ChunkingConfig(1, 0)
        candidates = chunk_document(document, strategy, config, Characters())
        assert any(candidate.content.isspace() for candidate in candidates)
        assert_output(document, candidates, strategy, config, Characters())


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_real_tokenizer_unicode_literal_special_and_independent_counts(
    strategy: ChunkStrategy,
) -> None:
    document = document_with_body("😀漢字e\u0301\n<|endoftext|> café 👩‍💻 " * 5)
    config = ChunkingConfig(19, 0 if strategy == "fixed" else 7)
    tokenizer = TiktokenTokenizer()
    candidates = chunk_document(document, strategy, config, tokenizer)
    encoding = tiktoken.get_encoding("cl100k_base")
    for candidate in candidates:
        assert candidate.token_count == len(
            encoding.encode(candidate.content, disallowed_special=())
        )
    assert_output(document, candidates, strategy, config, tokenizer)


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("location", ["body", "title", "path", "heading"])
def test_lone_surrogate_rejected_before_tokenizer(
    strategy: ChunkStrategy, location: str
) -> None:
    document = document_with_body("ordinary")
    if location == "body":
        document.introduction = [Paragraph([Text("bad\ud800")], SourceRange(3, 3))]
    elif location == "title":
        document.title = "bad\udfff"
    elif location == "path":
        document.source_path = "bad\ud800"
    else:
        document.sections = [
            Section("bad\udfff", 2, ["D", "bad\udfff"], SourceRange(7, 7))
        ]

    class MustNotEncode:
        def encode(self, text: str) -> list[int]:
            pytest.fail("Tokenizer called before Unicode validation")

    with pytest.raises(ChunkingError) as caught:
        chunk_document(document, strategy, tokenizer=MustNotEncode())
    assert caught.value.reason_code == "invalid_unicode"


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_unrepresentable_budget_raises_instead_of_partial_success(
    strategy: ChunkStrategy,
) -> None:
    # Earlier ASCII can fit, but the four-token character cannot fit even with
    # all overlap/context removed. No successful partial list may escape.
    document = document_with_body("a " * 10 + "𠮷")
    assert len(TiktokenTokenizer().encode("𠮷")) > 1
    with pytest.raises(ChunkingError) as caught:
        chunk_document(document, strategy, ChunkingConfig(1, 0), TiktokenTokenizer())
    assert caught.value.reason_code == "token_budget_unrepresentable"


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_nonmonotone_search_exhausts_later_endpoints(strategy: ChunkStrategy) -> None:
    document = document_with_body("a MAGIC")
    config = ChunkingConfig(1, 0)
    candidates = chunk_document(document, strategy, config, Nonmonotone())
    assert len(candidates) == 1
    assert not candidates[0].heading_prefix_omitted
    assert_output(document, candidates, strategy, config, Nonmonotone())


@pytest.mark.parametrize("strategy", ["fixed", "fixed_overlap"])
def test_fixed_end_and_overlap_match_exhaustive_reference(
    strategy: ChunkStrategy,
) -> None:
    document = document_with_body("abcdefghi" * 4)
    tokenizer = Characters()
    config = ChunkingConfig(11, 0 if strategy == "fixed" else 8)
    canonical = serialize_markdown(document).text
    cursor = previous_start = 0
    expected: list[tuple[int, int, int]] = []
    while cursor < len(canonical):
        starts = sorted(
            (
                start
                for start in range(previous_start, cursor)
                if len(tokenizer.encode(canonical[start:cursor]))
                <= config.overlap_tokens
            ),
            key=lambda start: (-len(tokenizer.encode(canonical[start:cursor])), start),
        ) + [cursor]
        choices = [
            (start, end)
            for start in starts
            for end in range(len(canonical), cursor, -1)
            if len(tokenizer.encode(canonical[start:end])) <= config.max_tokens
        ]
        start, end = choices[0]
        expected.append((start, cursor, end))
        previous_start, cursor = start, end
    candidates = chunk_document(document, strategy, config, tokenizer)
    assert [candidate.content for candidate in candidates] == [
        canonical[start:end] for start, _, end in expected
    ]
    assert [candidate.actual_overlap_tokens for candidate in candidates] == [
        cursor - start for start, cursor, _ in expected
    ]
    assert_output(document, candidates, strategy, config, tokenizer)


def test_fixed_window_crosses_heading_paths_without_generated_context() -> None:
    document = parse_markdown("# D\n\nintro\n\n## A\n\none\n\n### B\n\ntwo")
    for strategy in ("fixed", "fixed_overlap"):
        candidates = chunk_document(document, strategy)
        assert len(candidates) == 1
        assert candidates[0].content == serialize_markdown(document).text
        assert candidates[0].heading_paths == [["D"], ["D", "A"], ["D", "A", "B"]]
        assert SourceRange(1, 1) not in candidates[0].source_spans
        assert candidates[0].source_spans == [
            SourceRange(3, 3),
            SourceRange(5, 5),
            SourceRange(7, 7),
            SourceRange(9, 9),
            SourceRange(11, 11),
        ]


def test_heading_introduction_nested_skipped_levels_and_returning_parent_runs() -> None:
    child = Section(
        "Deep",
        4,
        ["D*", "S", "Deep"],
        SourceRange(9, 12),
        [Paragraph([Text("child")], SourceRange(11, 12))],
    )
    parent = Section(
        "S",
        2,
        ["D*", "S"],
        SourceRange(5, 16),
        [
            Paragraph([Text("before")], SourceRange(7, 7)),
            child,
            Paragraph([Text("after")], SourceRange(15, 16)),
        ],
    )
    document = ParsedDocument(
        "D*",
        None,
        [Paragraph([Text("intro")], SourceRange(3, 3))],
        [parent, Section("Empty", 2, ["D*", "Empty"], SourceRange(18, 18))],
    )
    config = ChunkingConfig(100, 50)
    candidates = chunk_document(document, "heading_aware", config, Characters())
    assert [candidate.heading_paths for candidate in candidates] == [
        [["D*"]],
        [["D*", "S"]],
        [["D*", "S", "Deep"]],
        [["D*", "S"]],
    ]
    assert [candidate.content for candidate in candidates] == [
        "# D\\*\n\nintro",
        "# D\\*\n## S\n\nbefore",
        "# D\\*\n## S\n#### Deep\n\nchild",
        "# D\\*\n## S\n\nafter",
    ]
    assert all(candidate.actual_overlap_tokens == 0 for candidate in candidates)
    assert [candidate.source_spans for candidate in candidates] == [
        [SourceRange(3, 3)],
        [SourceRange(5, 5), SourceRange(7, 7)],
        [SourceRange(5, 5), SourceRange(9, 9), SourceRange(11, 12)],
        [SourceRange(5, 5), SourceRange(15, 16)],
    ]
    assert_output(document, candidates, "heading_aware", config, Characters())


def test_every_candidate_prefix_and_necessary_omission() -> None:
    document = parse_markdown("# D*\n\n## S\n\n#### Deep\n\n" + "word " * 30)
    config = ChunkingConfig(55, 10)
    candidates = chunk_document(document, "heading_aware", config, Characters())
    assert len(candidates) > 2
    assert all(
        candidate.content.startswith("# D\\*\n## S\n#### Deep\n\n")
        for candidate in candidates
    )
    assert_output(document, candidates, "heading_aware", config, Characters())
    impossible = document_with_body("abcdefgh", "Title that exceeds budget")
    config = ChunkingConfig(4, 3)
    candidates = chunk_document(impossible, "heading_aware", config, Characters())
    assert all(candidate.heading_prefix_omitted for candidate in candidates)
    assert all(
        candidate.heading_paths == [[impossible.title]] for candidate in candidates
    )
    assert all(
        all(part.role != "context" for part in candidate.parts)
        for candidate in candidates
    )
    assert_output(impossible, candidates, "heading_aware", config, Characters())


def test_natural_overlap_whole_short_block_not_cut_intact_block() -> None:
    document = ParsedDocument(
        "D",
        None,
        [
            Paragraph([Text("abc")], SourceRange(3, 3)),
            Paragraph([Text("def")], SourceRange(5, 5)),
            Paragraph([Text("ghi")], SourceRange(7, 7)),
        ],
        [],
    )
    config = ChunkingConfig(13, 8)
    candidates = chunk_document(document, "heading_aware", config, Characters())
    assert candidates[0].content == "# D\n\nabc\n\ndef"
    assert candidates[1].actual_overlap_tokens == 3
    assert candidates[1].content == "# D\n\ndef\n\nghi"
    assert_output(document, candidates, "heading_aware", config, Characters())
    document.introduction[0] = Paragraph([Text("123456789")], SourceRange(3, 3))
    config = ChunkingConfig(14, 4)
    candidates = chunk_document(document, "heading_aware", config, Characters())
    assert (
        candidates[0].actual_overlap_tokens == candidates[1].actual_overlap_tokens == 0
    )
    assert_output(document, candidates, "heading_aware", config, Characters())


def test_overlap_reduced_before_fragmenting_next_intact_block() -> None:
    document = ParsedDocument(
        "D",
        None,
        [
            Paragraph([Text("abc")], SourceRange(3, 3)),
            Paragraph([Text("1234567890")], SourceRange(5, 5)),
        ],
        [],
    )
    config = ChunkingConfig(18, 8)
    candidates = chunk_document(document, "heading_aware", config, Characters())
    assert len(candidates) == 2
    assert candidates[1].actual_overlap_tokens == 0
    assert candidates[1].content.endswith("\n\n1234567890")
    assert_output(document, candidates, "heading_aware", config, Characters())


@pytest.mark.parametrize(
    "body",
    [
        "- first item\n- second item\n- " + "large " * 30,
        "```python\nfirst()\nsecond()\n" + "very_long_line" * 12 + "\n```",
        "> first paragraph\n>\n> second paragraph\n>\n> " + "large " * 30,
        "a paragraph " * 30,
        "> ### Embedded\n>\n> body " + "large " * 30,
    ],
)
def test_oversized_structural_units_and_character_fallback(body: str) -> None:
    document = parse_markdown("# D\n\n## S\n\n" + body)
    config = ChunkingConfig(44, 13)
    candidates = chunk_document(document, "heading_aware", config, Characters())
    assert len(candidates) > 1
    assert_output(document, candidates, "heading_aware", config, Characters())


@pytest.mark.parametrize("maximum", [1, 15, 40, 55])
def test_table_continuations_repeat_headers_as_context_not_source_or_overlap(
    maximum: int,
) -> None:
    document = parse_markdown(
        "# D\n\n## S\n\n| A | B |\n| --- | --- |\n| x | y |\n| z | w |\n| x | y |"
    )
    config = ChunkingConfig(maximum, maximum - 1)
    candidates = chunk_document(document, "heading_aware", config, Characters())
    assert_output(document, candidates, "heading_aware", config, Characters())
    header_parts = [
        (candidate, part)
        for candidate in candidates
        for part in candidate.parts
        if part.context_kind == "table_header"
    ]
    if maximum >= 40:
        assert header_parts
        header = serialize_markdown(document).runs[0].blocks[0].table_header
        assert header is not None
        for candidate, part in header_parts:
            assert candidate.content[part.output_start : part.output_end] == header
            assert part.canonical_start is part.canonical_end is None


@pytest.mark.parametrize(
    "mutation",
    [
        "ordinal",
        "strategy",
        "token_count",
        "content",
        "output_gap",
        "canonical_offset",
        "context_coverage",
        "context_kind",
        "heading_paths",
        "source_spans",
        "overlap_count",
        "prefix_flag",
        "drop_candidate",
        "duplicate_candidate",
        "source_path",
        "no_progress",
    ],
)
def test_validator_rejects_mutated_outputs(mutation: str) -> None:
    document = parse_markdown("# D\n\n## S\n\n" + "repeated prose " * 20)
    config = ChunkingConfig(40, 10)
    tokenizer = Characters()
    candidates = chunk_document(document, "heading_aware", config, tokenizer)
    broken = deepcopy(candidates)
    candidate = broken[1]
    if mutation == "ordinal":
        candidate.ordinal += 1
    elif mutation == "strategy":
        candidate.strategy = "fixed"
    elif mutation == "token_count":
        candidate.token_count += 1
    elif mutation == "content":
        candidate.content = "!" + candidate.content[1:]
    elif mutation == "output_gap":
        candidate.parts[0].output_start = 1
    elif mutation == "canonical_offset":
        candidate.parts[-1].canonical_start = 0
    elif mutation == "context_coverage":
        candidate.parts[0].canonical_start = 0
    elif mutation == "context_kind":
        candidate.parts[0].context_kind = None
    elif mutation == "heading_paths":
        candidate.heading_paths = [["invented"]]
    elif mutation == "source_spans":
        candidate.source_spans = [SourceRange(1, 999)]
    elif mutation == "overlap_count":
        candidate.actual_overlap_tokens += 1
    elif mutation == "prefix_flag":
        candidate.heading_prefix_omitted = True
    elif mutation == "drop_candidate":
        broken.pop()
    elif mutation == "duplicate_candidate":
        broken.append(deepcopy(broken[-1]))
    elif mutation == "source_path":
        candidate.source_path = "different.md"
    else:
        candidate.parts[-1] = replace(candidate.parts[-1], role="overlap")
    with pytest.raises(ChunkingError, match="invariant_"):
        validate_chunks(
            serialize_markdown(document), broken, "heading_aware", config, tokenizer
        )


def test_all_twelve_topics_are_present() -> None:
    assert len(TOPICS) == 12


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_literal_special_tokens_are_not_interpreted(strategy: ChunkStrategy) -> None:
    literal = "<|endoftext|><|fim_prefix|>"
    document = ParsedDocument("D", None, [RawHTMLBlock(literal, SourceRange(3, 3))], [])
    config = ChunkingConfig(500, 0 if strategy == "fixed" else 100)
    candidates = chunk_document(document, strategy, config)
    assert len(candidates) == 1
    assert literal in candidates[0].content
    assert_output(document, candidates, strategy, config, TiktokenTokenizer())


@pytest.mark.parametrize(
    "body",
    [
        "- one\n- two\n- three\n- four",
        "```python\none()\ntwo()\nthree()\nfour()\n```",
        "> one\n>\n> two\n>\n> three\n>\n> four",
    ],
)
def test_greedy_natural_units_before_character_fallback(body: str) -> None:
    document = parse_markdown("# D\n\n## S\n\n" + body)
    frozen = serialize_markdown(document)
    run = frozen.runs[0]
    boundaries = run.blocks[0].boundaries
    starts = [run.start, *boundaries[:-1]]
    maximum_unit = max(
        end - start for start, end in zip(starts, boundaries, strict=True)
    )
    prefix = "# D\n## S\n\n"
    config = ChunkingConfig(len(prefix) + maximum_unit, 0)
    candidates = chunk_document(document, "heading_aware", config, Characters())
    assert len(candidates) > 1
    cursor = run.start
    for candidate in candidates:
        source = [part for part in candidate.parts if part.role == "source"]
        expected_end = max(
            end
            for end in boundaries
            if cursor < end and len(prefix) + end - cursor <= config.max_tokens
        )
        assert source[-1].canonical_end == expected_end
        cursor = expected_end
    assert_output(document, candidates, "heading_aware", config, Characters())


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_no_source_rereads_or_network_after_parsing(
    strategy: ChunkStrategy, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = document_with_body("Already parsed source " * 10)
    tokenizer = TiktokenTokenizer()
    forbidden = Mock(side_effect=AssertionError("Unexpected I/O during chunking"))
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(socket, "connect", forbidden)
    config = ChunkingConfig(25, 0 if strategy == "fixed" else 5)
    candidates = chunk_document(document, strategy, config, tokenizer)
    assert_output(document, candidates, strategy, config, tokenizer)
    forbidden.assert_not_called()


def test_constructor_injection_and_call_overrides() -> None:
    document = document_with_body("abc " * 20)
    first = ChunkingConfig(15, 3)
    override = ChunkingConfig(30, 5)
    chunker = HeadingAwareChunker(first, Characters())
    assert chunker.chunk(document) == chunk_document(
        document, "heading_aware", first, Characters()
    )
    assert chunker.chunk(document, override, TiktokenTokenizer()) == chunk_document(
        document, "heading_aware", override, TiktokenTokenizer()
    )


@pytest.mark.parametrize("path", TOPICS, ids=lambda path: path.stem)
@pytest.mark.parametrize("strategy", STRATEGIES)
def test_whole_handbook_corpus(path: Path, strategy: ChunkStrategy) -> None:
    document = parse_markdown_file(path)
    original = deepcopy(document)
    config = ChunkingConfig(500, 0 if strategy == "fixed" else 100)
    tokenizer = TiktokenTokenizer()
    candidates = chunk_document(document, strategy, config, tokenizer)
    assert candidates
    assert candidates == chunk_document(document, strategy, config, tokenizer)
    assert document == original
    assert_output(document, candidates, strategy, config, tokenizer)
