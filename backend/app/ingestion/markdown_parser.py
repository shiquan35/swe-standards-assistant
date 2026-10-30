"""Parse one handbook topic into source-located nodes without ingestion side effects."""

import re
from os import PathLike, fspath
from pathlib import Path
from typing import Literal

from markdown_it import MarkdownIt
from markdown_it.rules_core import StateCore
from markdown_it.token import Token
from markdown_it.tree import SyntaxTreeNode
from mdit_py_plugins.tasklists import tasklists_plugin

from app.core.logger import app_logger
from app.ingestion.markdown_models import (
    Block,
    Blockquote,
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
)


class MarkdownParseError(ValueError):
    """Invalid handbook structure, identified without exposing source content."""

    def __init__(self, reason_code: str, line: int | None = None) -> None:
        self.reason_code = reason_code
        self.line = line
        super().__init__(reason_code)


def _capture_task_markers(state: StateCore) -> None:
    """Remember state before the plugin strips task markers from inline text."""
    for index in range(2, len(state.tokens)):
        token = state.tokens[index]
        if (
            token.type == "inline"
            and state.tokens[index - 1].type == "paragraph_open"
            and state.tokens[index - 2].type == "list_item_open"
            and re.match(r"\[[ xX]\][ \t\n\v\f\r]+", token.content)
        ):
            token.meta["handbook_checked"] = token.content[1] in "xX"


def _extract_task_state(state: StateCore) -> None:
    """Remove exactly the synthetic checkbox, never authored checkbox HTML."""
    for index in range(2, len(state.tokens)):
        token = state.tokens[index]
        if "handbook_checked" in token.meta and token.children:
            item = state.tokens[index - 2]
            if item.attrGet("class") == "task-list-item":
                item.meta["handbook_checked"] = token.meta["handbook_checked"]
                # Reparse the marker-free text: reference resolution may have
                # consumed [x] as a link before the plugin sliced its children.
                token.children = state.md.parseInline(token.content, state.env)[
                    0
                ].children


def _parser() -> MarkdownIt:
    parser = MarkdownIt("gfm-like", {"html": True}).use(tasklists_plugin)
    parser.core.ruler.before(
        "github-tasklists", "handbook-task-markers", _capture_task_markers
    )
    parser.core.ruler.after(
        "github-tasklists", "handbook-task-state", _extract_task_state
    )
    return parser


def _token(node: SyntaxTreeNode) -> Token:
    if node.token is not None:
        return node.token
    if node.nester_tokens is not None:
        return node.nester_tokens.opening
    raise ValueError("Expected a non-root Markdown node")


def _range(node: SyntaxTreeNode) -> SourceRange:
    mapping = _token(node).map
    if mapping is None:
        raise ValueError("Expected a block source map")
    return SourceRange(mapping[0] + 1, mapping[1])


def _inlines(nodes: list[SyntaxTreeNode]) -> list[Inline]:
    result: list[Inline] = []
    for node in nodes:
        token = _token(node)
        match node.type:
            case "inline":
                result.extend(_inlines(node.children))
            case "text":
                if token.content:
                    result.append(Text(token.content))
            case "em":
                result.append(Emphasis(_inlines(node.children)))
            case "strong":
                result.append(Strong(_inlines(node.children)))
            case "s":
                result.append(Strikethrough(_inlines(node.children)))
            case "code_inline":
                result.append(CodeSpan(token.content))
            case "link":
                result.append(
                    Link(str(token.attrGet("href") or ""), _inlines(node.children))
                )
            case "image":
                result.append(
                    Image(str(token.attrGet("src") or ""), _plain_text(node.children))
                )
            case "softbreak":
                result.append(SoftBreak())
            case "hardbreak":
                result.append(HardBreak())
            case "html_inline":
                result.append(RawHTMLInline(token.content))
            case _:
                result.append(Text(token.content))
    return result


def _plain_text(nodes: list[SyntaxTreeNode]) -> str:
    parts: list[str] = []
    for node in nodes:
        if node.type in {"softbreak", "hardbreak"}:
            parts.append(" ")
        elif node.children:
            parts.append(_plain_text(node.children))
        elif node.type != "html_inline":
            parts.append(_token(node).content)
    return "".join(parts)


def _table(node: SyntaxTreeNode, source_range: SourceRange) -> Table:
    header: list[list[Inline]] = []
    rows: list[list[list[Inline]]] = []
    for group in node.children:
        for row in group.children:
            cells = [_inlines(cell.children) for cell in row.children]
            if group.type == "thead":
                header = cells
            else:
                rows.append(cells)
    return Table(header, rows, source_range)


def _block(node: SyntaxTreeNode, inherited: SourceRange | None = None) -> Block:
    source_range = inherited if inherited is not None else _range(node)
    token = _token(node)
    match node.type:
        case "paragraph":
            return Paragraph(_inlines(node.children), source_range)
        case "heading":
            return HeadingBlock(
                int(token.tag[1:]), _inlines(node.children), source_range
            )
        case "bullet_list" | "ordered_list":
            items = [
                ListItem(
                    [_block(child, source_range) for child in item.children],
                    source_range,
                    _token(item).meta.get("handbook_checked"),
                )
                for item in node.children
            ]
            return ListBlock(
                node.type == "ordered_list",
                int(token.attrGet("start") or "1"),
                items,
                source_range,
            )
        case "blockquote":
            return Blockquote(
                [_block(child, source_range) for child in node.children], source_range
            )
        case "fence" | "code_block":
            language = token.info.split()[0] if token.info.strip() else None
            return CodeBlock(token.content, language, source_range)
        case "table":
            return _table(node, source_range)
        case "hr":
            return ThematicBreak(source_range)
        case "html_block":
            return RawHTMLBlock(token.content, source_range)
        case _:
            return Paragraph([Text(token.content)], source_range)


def _reject(reason_code: str, line: int | None = None) -> None:
    app_logger.bind(reason_code=reason_code, line=line).warning("markdown_invalid")
    raise MarkdownParseError(reason_code, line)


def _validate(nodes: list[SyntaxTreeNode], text: str) -> SyntaxTreeNode:
    if not text.strip():
        _reject("empty_document")
    headings = [node for node in nodes if node.type == "heading"]
    titles = [node for node in headings if _token(node).tag == "h1"]
    if not titles:
        _reject("missing_h1")
    if len(titles) != 1:
        _reject("multiple_h1", _range(titles[1]).start_line)
    if not any(_token(node).tag == "h2" for node in headings):
        _reject("missing_h2")
    title = titles[0]
    for node in nodes[: nodes.index(title)]:
        if (
            node.type != "html_block"
            or re.sub(r"<!--[\s\S]*?-->", "", _token(node).content).strip()
        ):
            _reject("content_before_h1", _range(node).start_line)
    # Inspect the actual source: link definitions produce no visible tokens but
    # are still forbidden pre-title content. Only complete HTML comments pass.
    preamble = "\n".join(text.split("\n")[: _range(title).start_line - 1])
    if re.sub(r"<!--[\s\S]*?-->", "", preamble).strip():
        _reject("content_before_h1", 1)
    return title


def _parse(
    text: str, source_path: str | None, source_kind: Literal["text", "file"]
) -> ParsedDocument:
    app_logger.bind(
        function="parse_markdown", source_kind=source_kind, input_chars=len(text)
    ).debug("markdown_parse_entry")
    # Match markdown-it's line-ending normalization, not str.splitlines(), which
    # also treats Unicode paragraph separators as new source lines.
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    nodes = SyntaxTreeNode(_parser().parse(normalized)).children
    title_node = _validate(nodes, normalized)
    title = _plain_text(title_node.children)
    document = ParsedDocument(title, source_path, [], [])
    line_count = len(normalized.split("\n")) - int(normalized.endswith("\n"))
    stack: list[Section] = []
    for node in nodes[nodes.index(title_node) + 1 :]:
        if node.type != "heading":
            block = _block(node)
            if stack:
                stack[-1].children.append(block)
            else:
                document.introduction.append(block)
            continue
        level = int(_token(node).tag[1:])
        source_range = _range(node)
        while stack and stack[-1].level >= level:
            stack.pop().source_range.end_line = source_range.start_line - 1
        heading = _plain_text(node.children)
        heading_path = [*stack[-1].heading_path, heading] if stack else [title, heading]
        section = Section(
            heading,
            level,
            heading_path,
            SourceRange(source_range.start_line, line_count),
        )
        if stack:
            stack[-1].children.append(section)
        else:
            document.sections.append(section)
        stack.append(section)
    app_logger.bind(
        function="parse_markdown",
        section_count=sum(node.type == "heading" for node in nodes) - 1,
        source_ranges=[
            (section.source_range.start_line, section.source_range.end_line)
            for section in document.sections
        ],
        block_types=sorted({node.type for node in nodes if node.type != "heading"}),
    ).debug("markdown_parse_success")
    return document


def parse_markdown(text: str, source_path: str | None = None) -> ParsedDocument:
    """Parse one topic; empty bodies are valid, invalid document shape is not."""
    return _parse(text, source_path, "text")


def parse_markdown_file(path: str | PathLike[str]) -> ParsedDocument:
    """Read strict UTF-8, preserving the supplied path and ordinary I/O errors."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as error:
        app_logger.bind(error_type=type(error).__name__).error("markdown_file_error")
        raise
    return _parse(text, fspath(path), "file")
