"""Output-focused parser regression tests; no database or embedding services."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from app.core.logger import app_logger
from app.ingestion import (
    Block,
    Blockquote,
    CodeBlock,
    CodeSpan,
    Emphasis,
    HardBreak,
    HeadingBlock,
    Image,
    Link,
    ListBlock,
    MarkdownParseError,
    Paragraph,
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
)

if TYPE_CHECKING:
    from loguru import Message

HANDBOOK = Path(__file__).parents[2] / "knowledge_base" / "engineering-handbook"
TOPICS = sorted(path for path in HANDBOOK.glob("*.md") if path.name != "README.md")


def _sections(sections: list[Section]) -> Iterator[Section]:
    for section in sections:
        yield section
        yield from _sections(
            [child for child in section.children if isinstance(child, Section)]
        )


def _body(body: str) -> list[Block | Section]:
    return parse_markdown("# Title\n\n## Section\n\n" + body).sections[0].children


@pytest.mark.parametrize("path", TOPICS, ids=lambda path: path.stem)
def test_handbook_topics(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    document = parse_markdown_file(path)
    assert len(TOPICS) == 12
    assert document.title == text.splitlines()[0].removeprefix("# ")
    assert document.source_path == str(path)
    assert document.sections
    for section in _sections(document.sections):
        assert section.heading_path[0] == document.title
        assert section.heading_path[-1] == section.heading
        assert (
            1
            <= section.source_range.start_line
            <= section.source_range.end_line
            <= len(text.splitlines())
        )
        for child in section.children:
            assert section.source_range.start_line <= child.source_range.start_line
            assert child.source_range.end_line <= section.source_range.end_line


def test_section_order_paths_and_ownership() -> None:
    document = parse_markdown(
        "# Title\n\nIntroduction.\n\n## A\nBefore.\n### B\nAfter B.\n"
        "#### C\nAfter C.\n## A\n#### Skipped\nLast.\n"
    )
    assert document.introduction == [
        Paragraph([Text("Introduction.")], SourceRange(3, 3))
    ]
    first, duplicate = document.sections
    assert first.heading == duplicate.heading == "A"
    assert first is not duplicate
    assert first.source_range == SourceRange(5, 10)
    paragraph, child = first.children
    assert isinstance(paragraph, Paragraph)
    assert isinstance(child, Section)
    assert child.heading_path == ["Title", "A", "B"]
    assert isinstance(child.children[0], Paragraph)
    assert child.children[0].children == [Text("After B.")]
    grandchild = child.children[1]
    assert isinstance(grandchild, Section)
    assert grandchild.heading_path == ["Title", "A", "B", "C"]
    skipped = duplicate.children[0]
    assert isinstance(skipped, Section)
    assert skipped.level == 4
    assert skipped.heading_path == ["Title", "A", "Skipped"]


def test_empty_introduction_sections_and_parent_with_only_subsection() -> None:
    document = parse_markdown("# Title\n## Empty\n## Parent\n### Child\n")
    assert document.introduction == []
    empty, parent = document.sections
    assert empty.children == []
    assert empty.source_range == SourceRange(2, 2)
    assert len(parent.children) == 1
    child = parent.children[0]
    assert isinstance(child, Section)
    assert child.children == []
    assert child.source_range == SourceRange(4, 4)


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize(
    "trailing, end", [("", 4), ("\n", 4), ("\n\n", 5), ("\n\n\n", 6)]
)
def test_logical_line_ranges(ending: str, trailing: str, end: int) -> None:
    text = ("# Title\n\n## Section\nBody" + trailing).replace("\n", ending)
    section = parse_markdown(text).sections[0]
    assert section.source_range == SourceRange(3, end)
    assert section.children[0].source_range == SourceRange(4, 4)


def test_blank_lines_before_heading_and_unicode_separator() -> None:
    first, second = parse_markdown("# T\n## A\np\n\n\n## B\nx\u2028y\n").sections
    assert first.source_range == SourceRange(2, 5)
    assert second.source_range == SourceRange(6, 7)


def test_nested_lists_task_state_and_authored_checkbox() -> None:
    blocks = _body(
        '- [x] Done <input type="checkbox">\n'
        "  - [ ] Todo\n"
        "  - [X]\tUpper\n"
        "- Ordinary\n\n"
        "3. Three\n4. Four\n"
    )
    tasks, ordered = blocks
    assert isinstance(tasks, ListBlock)
    assert not tasks.ordered
    assert [item.checked for item in tasks.items] == [True, None]
    done, nested = tasks.items[0].children
    assert isinstance(done, Paragraph)
    assert done.children[-1] == RawHTMLInline('<input type="checkbox">')
    assert isinstance(nested, ListBlock)
    assert [item.checked for item in nested.items] == [False, True]
    assert isinstance(nested.items[0].children[0], Paragraph)
    assert all(
        child.source_range == tasks.source_range
        for item in tasks.items
        for child in item.children
    )
    assert nested.items[0].children[0].source_range == tasks.source_range
    assert isinstance(ordered, ListBlock)
    assert ordered.ordered and ordered.start == 3


def test_authored_checkbox_matching_plugin_markup_is_not_removed() -> None:
    checkbox = '<input class="task-list-item-checkbox" checked="checked" disabled="disabled" type="checkbox">'
    blocks = _body(f"- [x] {checkbox}\n- Ordinary {checkbox}\n")
    tasks = blocks[0]
    assert isinstance(tasks, ListBlock)
    for item in tasks.items:
        paragraph = item.children[0]
        assert isinstance(paragraph, Paragraph)
        assert RawHTMLInline(checkbox) in paragraph.children


@pytest.mark.parametrize("marker, checked", [("x", True), ("X", True), (" ", False)])
def test_task_marker_reference_link_collision(marker: str, checked: bool) -> None:
    document = parse_markdown(f"# T\n## S\n- [{marker}] task\n\n[x]: /target\n")
    listing = document.sections[0].children[0]
    assert isinstance(listing, ListBlock)
    assert listing.items[0].checked is checked
    paragraph = listing.items[0].children[0]
    assert isinstance(paragraph, Paragraph)
    assert paragraph.children == [Text(" task")]


def test_task_content_keeps_automatic_links() -> None:
    listing = _body("- [x] https://example.com\n")[0]
    assert isinstance(listing, ListBlock)
    paragraph = listing.items[0].children[0]
    assert isinstance(paragraph, Paragraph)
    assert (
        Link("https://example.com", [Text("https://example.com")]) in paragraph.children
    )


def test_table_cells_and_gfm_pipe_semantics() -> None:
    table = _body(
        "| A | B | C |\n|---|---|---|\n"
        "| x\\|y | `a\\|b` | **strong** |\n"
        "| | empty | |\n| short |\n| a | b | c | ignored |\n"
    )[0]
    assert isinstance(table, Table)
    assert table.header == [[Text("A")], [Text("B")], [Text("C")]]
    assert table.rows[0] == [
        [Text("x|y")],
        [CodeSpan("a|b")],
        [Strong([Text("strong")])],
    ]
    assert table.rows[1] == [[], [Text("empty")], []]
    assert table.rows[2] == [[Text("short")], [], []]
    assert table.rows[3] == [[Text("a")], [Text("b")], [Text("c")]]
    unescaped = _body("| A | B |\n|---|---|\n| `x|y` |\n")[0]
    assert isinstance(unescaped, Table)
    assert unescaped.rows == [[[Text("`x")], [Text("y`")]]]


def test_inline_nodes_and_plain_text_heading_paths() -> None:
    document = parse_markdown(
        "# **Title** `code`\n## [Section](https://example.com)\n\n"
        "*em* **strong** ~~gone~~ `code` [link](https://example.com) "
        "![*alt*](image.png)\nsoft  \nhard\n"
    )
    section = document.sections[0]
    assert document.title == "Title code"
    assert section.heading_path == ["Title code", "Section"]
    paragraph = section.children[0]
    assert isinstance(paragraph, Paragraph)
    for node in [
        Emphasis([Text("em")]),
        Strong([Text("strong")]),
        Strikethrough([Text("gone")]),
        CodeSpan("code"),
        Link("https://example.com", [Text("link")]),
        Image("image.png", "alt"),
        SoftBreak(),
        HardBreak(),
    ]:
        assert node in paragraph.children
    linked = _body("https://example.com")[0]
    assert isinstance(linked, Paragraph)
    assert isinstance(linked.children[0], Link)


def test_code_quotes_html_and_unsupported_extensions() -> None:
    blocks = _body(
        "```python extra\n# Not a title\n  x = 1  \n```\n\n"
        "> quote\n>\n> - item\n\n---\n\n<div>opaque</div>\n\n"
        "    indented\n\n$math$ :emoji: [^footnote]\n"
    )
    code, quote, rule, html, indented, unknown = blocks
    assert isinstance(code, CodeBlock)
    assert code.language == "python"
    assert code.content == "# Not a title\n  x = 1  \n"
    assert isinstance(quote, Blockquote)
    assert isinstance(quote.children[1], ListBlock)
    assert quote.children[1].source_range == quote.source_range
    assert isinstance(rule, ThematicBreak)
    assert isinstance(html, RawHTMLBlock)
    assert html.content == "<div>opaque</div>\n"
    assert isinstance(indented, CodeBlock)
    assert indented.language is None
    assert indented.content == "indented\n"
    assert isinstance(unknown, Paragraph)
    assert unknown.children == [Text("$math$ :emoji: [^footnote]")]


def test_container_headings_do_not_change_document_outline() -> None:
    section = parse_markdown(
        "# Title\n## Section\n> # Quoted title\n\n- ### Item heading\n"
    ).sections[0]
    quote, listing = section.children
    assert isinstance(quote, Blockquote)
    assert isinstance(quote.children[0], HeadingBlock)
    assert isinstance(listing, ListBlock)
    assert isinstance(listing.items[0].children[0], HeadingBlock)
    assert section.heading_path == ["Title", "Section"]


@pytest.mark.parametrize(
    "preamble", ["", "\n\n", "<!-- comment -->\n", "<!-- multi\nline -->\n\n"]
)
def test_allowed_preamble(preamble: str) -> None:
    assert parse_markdown(preamble + "# Title\n## Section").title == "Title"


@pytest.mark.parametrize(
    "preamble", ["    <!-- comment -->\n\n", "```\n<!-- comment -->\n```\n"]
)
def test_comment_text_inside_code_is_not_an_allowed_preamble(preamble: str) -> None:
    with pytest.raises(MarkdownParseError, match="content_before_h1"):
        parse_markdown(preamble + "# Title\n## Section")


@pytest.mark.parametrize(
    "text, reason",
    [
        ("", "empty_document"),
        (" \n\t", "empty_document"),
        ("## Section", "missing_h1"),
        ("# A\n# B\n## Section", "multiple_h1"),
        ("# A\n### Section", "missing_h2"),
        ("content\n\n# A\n## B", "content_before_h1"),
        ("<div>visible</div>\n\n# A\n## B", "content_before_h1"),
        ("<!-- comment -->visible\n\n# A\n## B", "content_before_h1"),
        ("[ref]: https://example.com\n# A\n## B", "content_before_h1"),
    ],
)
def test_invalid_document(text: str, reason: str) -> None:
    with pytest.raises(MarkdownParseError) as caught:
        parse_markdown(text)
    assert caught.value.reason_code == reason


def test_file_api_paths_utf8_and_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "topic.md"
    text = "# Títle\n## Section\nBody\n"
    path.write_text(text, encoding="utf-8")
    for supplied in [path, str(path), "topic.md", "./topic.md"]:
        document = parse_markdown_file(supplied)
        assert document == parse_markdown(text, str(supplied))
    with pytest.raises(FileNotFoundError):
        parse_markdown_file("missing.md")
    path.write_bytes(b"\xff")
    with pytest.raises(UnicodeDecodeError):
        parse_markdown_file(path)


def test_logs_do_not_contain_source_or_exception_messages(tmp_path: Path) -> None:
    messages: list[str] = []

    def sink(message: Message) -> None:
        messages.append(
            json.dumps(
                {"message": message.record["message"], "extra": message.record["extra"]}
            )
        )

    handler = app_logger.add(sink, level="DEBUG")
    try:
        parse_markdown("# SecretTitle\n## SecretHeading\nSecretBody", "SecretPath")
        with pytest.raises(MarkdownParseError):
            parse_markdown("SecretPreamble\n# Title\n## Section", "SecretPath")
        with patch.object(Path, "read_text", side_effect=OSError("SecretError")):
            with pytest.raises(OSError):
                parse_markdown_file(tmp_path / "SecretPath")
    finally:
        app_logger.remove(handler)
    assert len(messages) == 5
    assert "Secret" not in "".join(messages)


def test_output_contains_no_library_or_persistence_objects() -> None:
    document = parse_markdown("# Title\n## Section\nBody")
    assert asdict(document)["sections"][0]["heading"] == "Section"
    assert document.source_path is None
