"""Canonical layout, semantic visitors, and offset provenance without services."""

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import pytest

from app.ingestion import (
    Block,
    Blockquote,
    ChunkingError,
    CodeBlock,
    CodeSpan,
    Emphasis,
    HardBreak,
    HeadingBlock,
    Image,
    Inline,
    Link,
    ListBlock,
    ListItem,
    Paragraph,
    ParsedDocument,
    RawHTMLBlock,
    RawHTMLInline,
    Section,
    SoftBreak,
    SourceRange,
    Strikethrough,
    Strong,
    Table,
    Text,
    ThematicBreak,
    parse_markdown,
    parse_markdown_file,
    serialize_markdown,
)


def _paragraph(text: str, line: int = 3) -> Paragraph:
    return Paragraph([Text(text)], SourceRange(line, line))


def _document(*blocks: Block) -> ParsedDocument:
    return ParsedDocument("Title", "not-reread.md", list(blocks), [])


def _body(block: Block) -> str:
    serialized = serialize_markdown(_document(block))
    run = serialized.runs[0]
    return serialized.text[run.start : run.end]


@pytest.mark.parametrize(
    "node, expected",
    [
        (
            Text(r"*literal* [x] &entity; <tag> 1. a|b \\"),
            r"\*literal\* \[x\] \&entity; \<tag\> 1\. a\|b \\\\",
        ),
        (Emphasis([Text("em")]), "*em*"),
        (Strong([Text("strong")]), "**strong**"),
        (Strikethrough([Text("gone")]), "~~gone~~"),
        (Strong([Emphasis([Text("nested")])]), "**_nested_**"),
        (CodeSpan("code"), "`code`"),
        (CodeSpan("a``b"), "```a``b```"),
        (CodeSpan("`edge`"), "`` `edge` ``"),
        (CodeSpan(" padded "), "`  padded  `"),
        (CodeSpan("   "), "`   `"),
        (
            Link("https://example.test/a (b)>|", [Strong([Text("link")])]),
            "[**link**](<https://example.test/a%20(b)%3E%7C>)",
        ),
        (Image("img a.png", "[alt]*"), r"![\[alt\]\*](<img%20a.png>)"),
        (SoftBreak(), "\n"),
        (HardBreak(), "  \n"),
        (RawHTMLInline('<b data-x="&">opaque</b>'), '<b data-x="&">opaque</b>'),
    ],
)
def test_every_inline(node: Inline, expected: str) -> None:
    assert _body(Paragraph([node], SourceRange(3, 3))) == expected


@pytest.mark.parametrize(
    "content", ["a``b", "`edge`", " padded ", "   ", "a|b", r"a\|b"]
)
def test_code_spans_round_trip_in_and_out_of_tables(content: str) -> None:
    for in_table in [False, True]:
        block: Block = (
            Table([[Text("H")]], [[[CodeSpan(content)]]], SourceRange(3, 5))
            if in_table
            else Paragraph([CodeSpan(content)], SourceRange(3, 3))
        )
        parsed = parse_markdown("# T\n## S\n" + _body(block)).sections[0].children[0]
        if isinstance(parsed, Table):
            assert parsed.rows[0][0] == [CodeSpan(content)]
        else:
            assert isinstance(parsed, Paragraph)
            assert parsed.children == [CodeSpan(content)]


def test_all_blocks_and_exact_layout() -> None:
    span = SourceRange(3, 20)
    listing = ListBlock(
        True,
        7,
        [
            ListItem(
                [
                    _paragraph("done"),
                    ListBlock(
                        False, 1, [ListItem([_paragraph("nested")], span, False)], span
                    ),
                ],
                span,
                True,
            ),
            ListItem([_paragraph("ordinary"), _paragraph("second paragraph")], span),
        ],
        span,
    )
    quote = Blockquote(
        [
            _paragraph("quote"),
            HeadingBlock(4, [Text("inside")], span),
            ThematicBreak(span),
        ],
        span,
    )
    table = Table(
        [[Text("A")], [Text("B")]],
        [[[Text("x|y")], [CodeSpan("a|b")]], [[], [Strong([Text("bold")])]]],
        span,
    )
    document = _document(
        listing,
        quote,
        CodeBlock("one\ntwo\n", "python", span),
        table,
        RawHTMLBlock("<div>opaque</div>\n", span),
    )
    serialized = serialize_markdown(document)
    assert serialized.text == (
        "# Title\n\n7. [x] done\n   \n   - [ ] nested\n\n"
        "8. ordinary\n   \n   second paragraph\n\n"
        "> quote\n>\n> #### inside\n>\n> ---\n\n"
        "```python\none\ntwo\n```\n\n"
        "| A | B |\n| --- | --- |\n| x\\|y | `a\\|b` |\n|  | **bold** |\n\n"
        "<div>opaque</div>\n"
    )
    run = serialized.runs[0]
    assert len(run.blocks) == 5
    assert [len(block.boundaries) for block in run.blocks] == [2, 3, 2, 3, 1]
    table_block = run.blocks[3]
    assert table_block.table_header == "| A | B |\n| --- | --- |"
    for block in run.blocks:
        assert block.boundaries == sorted(set(block.boundaries))
        assert block.boundaries[-1] == block.end
        assert all(block.start < end <= block.end for end in block.boundaries)
    assert run.start == len("# Title\n\n")
    assert run.end == len(serialized.text)


@pytest.mark.parametrize("language", [None, "python", "lang`tick"])
def test_dynamic_code_fences_and_payload_preservation(language: str | None) -> None:
    content = "````\n~~~~~\n  keep spaces  \n\n"
    canonical = _body(CodeBlock(content, language, SourceRange(3, 9)))
    parsed = parse_markdown("# T\n## S\n" + canonical).sections[0].children[0]
    assert isinstance(parsed, CodeBlock)
    assert parsed.content == content
    assert parsed.language == language
    assert canonical.startswith("~~~~~~" if language == "lang`tick" else "`````")


def test_code_without_terminal_lf_and_unicode_line_separator() -> None:
    block = CodeBlock("a\u2028b\nlast", None, SourceRange(3, 6))
    serialized = serialize_markdown(_document(block))
    mapped = serialized.runs[0].blocks[0]
    assert serialized.text[mapped.start : mapped.end] == "```\na\u2028b\nlast\n```"
    assert len(mapped.boundaries) == 2


def test_source_order_runs_skipped_levels_and_ranges() -> None:
    intro = _paragraph("intro", 3)
    before, after = _paragraph("same", 6), _paragraph("same", 13)
    nested = Section(
        "Child",
        5,
        ["Title", "Parent", "Child"],
        SourceRange(8, 11),
        [_paragraph("child", 10)],
    )
    parent = Section(
        "Parent", 2, ["Title", "Parent"], SourceRange(5, 13), [before, nested, after]
    )
    empty = Section("Empty", 4, ["Title", "Empty"], SourceRange(15, 15))
    document = ParsedDocument("Title", "private-path", [intro], [parent, empty])
    original = deepcopy(document)
    with patch.object(Path, "read_text", side_effect=AssertionError("no file reads")):
        serialized = serialize_markdown(document)
    assert document == original
    assert serialized == serialize_markdown(document)
    assert (
        serialized.text
        == "# Title\n\nintro\n\n## Parent\n\nsame\n\n##### Child\n\nchild\n\nsame\n\n#### Empty"
    )
    assert [serialized.text[run.start : run.end] for run in serialized.runs] == [
        "intro",
        "same",
        "child",
        "same",
    ]
    assert [run.heading_levels for run in serialized.runs] == [
        [1],
        [1, 2],
        [1, 2, 5],
        [1, 2],
    ]
    assert [run.heading_path for run in serialized.runs] == [
        ["Title"],
        parent.heading_path,
        nested.heading_path,
        parent.heading_path,
    ]
    assert serialized.segments[0].source_range is None
    assert [
        segment.source_range for segment in serialized.segments if segment.source_range
    ] == [
        SourceRange(3, 3),
        SourceRange(5, 5),
        before.source_range,
        SourceRange(8, 8),
        SourceRange(10, 10),
        after.source_range,
        SourceRange(15, 15),
    ]
    cursor = 0
    for segment in serialized.segments:
        assert segment.start == cursor
        assert segment.start < segment.end
        cursor = segment.end
    assert cursor == len(serialized.text)
    # Metadata is copied, never an alias into parser-owned mutable paths/ranges.
    serialized.runs[1].heading_path.append("changed")
    for segment in serialized.segments:
        if segment.source_range:
            segment.source_range.end_line = 999
    assert document == original


def test_interblock_separators_are_inside_run_and_have_no_invented_span() -> None:
    serialized = serialize_markdown(
        _document(_paragraph("first"), _paragraph("second", 6))
    )
    run = serialized.runs[0]
    assert serialized.text[run.start : run.end] == "first\n\nsecond"
    assert serialized.text[run.blocks[0].end : run.blocks[1].start] == "\n\n"
    assert serialized.segments[-2].source_range is None


def test_nested_provenance_stays_coarse_and_html_stays_opaque() -> None:
    source = '<script src="https://do-not-fetch.invalid">secret()</script>\n'
    span = SourceRange(3, 9)
    quote = Blockquote([RawHTMLBlock(source, span), _paragraph("second")], span)
    serialized = serialize_markdown(_document(quote))
    source_segments = [
        segment for segment in serialized.segments if segment.source_range
    ]
    assert len(source_segments) == 1
    assert source_segments[0].source_range == span
    assert "> " + source in serialized.text


def test_empty_heading_only_and_whitespace_bodies() -> None:
    assert serialize_markdown(ParsedDocument("Title", None, [], [])).text == ""
    assert serialize_markdown(ParsedDocument("Title", None, [], [])).runs == []
    heading_only = serialize_markdown(parse_markdown("# Title\n## Empty\n#### Child"))
    assert heading_only.text == "# Title\n\n## Empty\n\n#### Child"
    assert heading_only.runs == []
    assert _body(_paragraph(" \t\n ")) == " \t\n "


@pytest.mark.parametrize(
    "location",
    [
        "title",
        "source_path",
        "heading",
        "heading_path",
        "text",
        "html",
        "code",
        "destination",
        "alt",
        "language",
    ],
)
def test_surrogates_rejected_anywhere_before_serialization(location: str) -> None:
    invalid = "private\ud800text"
    document = _document(_paragraph("valid"))
    section = Section("S", 2, ["Title", "S"], SourceRange(5, 9))
    document.sections.append(section)
    match location:
        case "title":
            document.title = invalid
        case "source_path":
            document.source_path = invalid
        case "heading":
            section.heading = invalid
        case "heading_path":
            section.heading_path.append(invalid)
        case "text":
            document.introduction = [_paragraph(invalid)]
        case "html":
            document.introduction = [RawHTMLBlock(invalid, SourceRange(3, 3))]
        case "code":
            document.introduction = [CodeBlock(invalid, None, SourceRange(3, 3))]
        case "destination":
            document.introduction = [Paragraph([Link(invalid, [])], SourceRange(3, 3))]
        case "alt":
            document.introduction = [
                Paragraph([Image("valid", invalid)], SourceRange(3, 3))
            ]
        case "language":
            document.introduction = [CodeBlock("valid", invalid, SourceRange(3, 3))]
    with pytest.raises(ChunkingError, match="^invalid_unicode$") as caught:
        serialize_markdown(document)
    assert caught.value.reason_code == "invalid_unicode"
    assert "private" not in str(caught.value)


def test_serialization_and_unicode_errors_do_not_log() -> None:
    with patch("app.core.logger.app_logger._log") as log:
        serialize_markdown(_document(_paragraph("private text")))
        with pytest.raises(ChunkingError):
            serialize_markdown(_document(_paragraph("private\udfff")))
    log.assert_not_called()


def test_all_handbook_topics_have_complete_maps() -> None:
    handbook = Path(__file__).parents[2] / "knowledge_base" / "engineering-handbook"
    topics = sorted(path for path in handbook.glob("*.md") if path.name != "README.md")
    assert len(topics) == 12
    for path in topics:
        document = parse_markdown_file(path)
        original = deepcopy(document)
        serialized = serialize_markdown(document)
        assert serialized == serialize_markdown(document)
        assert document == original
        reparsed = parse_markdown(serialized.text, document.source_path)
        assert _without_ranges(asdict(reparsed)) == _without_ranges(asdict(document))
        assert serialized.text
        assert serialized.segments[0].start == 0
        assert serialized.segments[-1].end == len(serialized.text)
        assert all(
            left.end == right.start
            for left, right in zip(
                serialized.segments, serialized.segments[1:], strict=False
            )
        )
        for run in serialized.runs:
            assert len(run.heading_levels) == len(run.heading_path)
            assert run.start == run.blocks[0].start
            assert run.end == run.blocks[-1].end


def _without_ranges(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _without_ranges(child)
            for key, child in value.items()
            if key != "source_range"
        }
    if isinstance(value, list):
        return [_without_ranges(child) for child in value]
    return value


@pytest.mark.parametrize(
    "body",
    [
        "*a*_b_",
        "**a**__b__",
        "*outer _inner_ end*",
        "**outer __inner__ end**",
        "word*em*word **strong** *with **nested** strong*",
        r"\*literal\* \[x\] &amp; &lt;tag&gt; 1\. a\|b",
        "[label](<https://example.test/a(b)>) ![alt](image.png)",
    ],
)
def test_inline_semantics_round_trip(body: str) -> None:
    original = parse_markdown("# T\n## S\n" + body)
    paragraph = original.sections[0].children[0]
    assert isinstance(paragraph, Paragraph)
    canonical = serialize_markdown(original)
    parsed = parse_markdown(canonical.text).sections[0].children[0]
    assert isinstance(parsed, Paragraph)
    assert paragraph.children == parsed.children
