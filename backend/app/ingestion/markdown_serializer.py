"""Canonical AST visitor and immutable-by-convention character coverage map.

Outline headings and direct blocks are joined with two newlines, without a
synthetic trailing newline. Raw HTML and code payloads are not stripped. Each
separator has its own segment (the following node's path, no source range).
Only inter-block separators inside a direct body belong to a BodyRun. No
serialization operation logs, renders HTML, rereads a file, or fetches a URL.
"""

import re
from dataclasses import dataclass, fields, is_dataclass
from urllib.parse import quote

from app.ingestion.chunk_models import (
    BodyRun,
    SerializedBlock,
    SerializedMarkdown,
    SerializedSegment,
)
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
from app.ingestion.tokenizer import validate_unicode


def _validate_tree(value: object) -> None:
    """Validate even metadata/empty AST strings before emitting any text."""
    if isinstance(value, str):
        validate_unicode(value)
    elif isinstance(value, list):
        for item in value:
            _validate_tree(item)
    elif is_dataclass(value) and not isinstance(value, type):
        for attribute in fields(value):
            _validate_tree(getattr(value, attribute.name))


def _escape(text: str) -> str:
    # Escape entity starts, autolinks, task markers and block-openers as well as
    # inline delimiters. Markdown backslash escapes preserve their literal text.
    return re.sub(r"([\\`*{}\[\]()<>#+\-.!_|~&])", r"\\\1", text)


def _destination(text: str) -> str:
    # Angle destinations permit parentheses; encode delimiters/whitespace and
    # backslashes rather than letting an authored destination close the link.
    return "<" + quote(text, safe="/:#?@!$&'()*+,;=+%~.-_") + ">"


def _code_span(content: str) -> str:
    width = max((len(run) for run in re.findall(r"`+", content)), default=0) + 1
    fence = "`" * width
    pad = (
        content.startswith("`")
        or content.endswith("`")
        or (
            content.startswith(" ")
            and content.endswith(" ")
            and bool(content.strip(" "))
        )
    )
    return fence + (" " if pad else "") + content + (" " if pad else "") + fence


def _inlines(
    nodes: list[Inline], *, table: bool = False, emphasis_marker: str = "*"
) -> str:
    parts: list[str] = []
    last_marker: str | None = None
    for node in nodes:
        previous_marker = last_marker
        last_marker = None
        match node:
            case Text(content):
                parts.append(_escape(content))
            case Emphasis(children) | Strong(children):
                # Adjacent equal delimiters would merge (*a**b*); alternate
                # markers for siblings and nesting without adding source text.
                marker = emphasis_marker
                if marker == previous_marker:
                    marker = "_" if marker == "*" else "*"
                last_marker = marker
                delimiter = marker * (2 if isinstance(node, Strong) else 1)
                body = _inlines(
                    children,
                    table=table,
                    emphasis_marker="_" if marker == "*" else "*",
                )
                parts.append(delimiter + body + delimiter)
            case Strikethrough(children):
                parts.append("~~" + _inlines(children, table=table) + "~~")
            case CodeSpan(content):
                parts.append(
                    _code_span(content.replace("|", r"\|") if table else content)
                )
            case Link(destination, children):
                parts.append(
                    "["
                    + _inlines(children, table=table)
                    + "]("
                    + _destination(destination)
                    + ")"
                )
            case Image(destination, alt_text):
                parts.append(
                    "![" + _escape(alt_text) + "](" + _destination(destination) + ")"
                )
            case SoftBreak():
                parts.append("\n")
            case HardBreak():
                parts.append("  \n")
            case RawHTMLInline(content):
                parts.append(content.replace("|", r"\|") if table else content)
    return "".join(parts)


@dataclass
class _Rendered:
    text: str
    boundaries: list[int]
    table_header: str | None = None


def _units(units: list[str], separator: str) -> _Rendered:
    """Attach separators to preceding units, keeping final end exactly len(text)."""
    text = separator.join(units)
    ends: list[int] = []
    offset = 0
    for index, unit in enumerate(units):
        offset += len(unit) + (len(separator) if index + 1 < len(units) else 0)
        if offset and (not ends or offset > ends[-1]):
            ends.append(offset)
    return _Rendered(text, ends)


def _block(node: Block) -> _Rendered:
    match node:
        case Paragraph(children):
            text = _inlines(children)
        case HeadingBlock(level, children):
            text = "#" * level + " " + _inlines(children)
        case ThematicBreak():
            text = "---"
        case RawHTMLBlock(content):
            text = content
        case CodeBlock(content, language):
            marker = "~" if language and "`" in language else "`"
            longest = max(
                (len(run) for run in re.findall(re.escape(marker) + "+", content)),
                default=0,
            )
            width = max(3, longest + 1)
            fence = marker * width
            opening = fence + (language or "") + "\n"
            payload = content + ("\n" if content and not content.endswith("\n") else "")
            # str.splitlines treats Unicode separators as line boundaries; only
            # literal LF creates canonical Markdown code-line boundaries.
            lines = payload.split("\n")
            units = [line + "\n" for line in lines[:-1]]
            if not units:
                units = [""]
            units[0] = opening + units[0]
            units[-1] += fence
            return _units(units, "")
        case ListBlock(ordered, start, items):
            units = []
            for index, item in enumerate(items):
                marker = f"{start + index}. " if ordered else "- "
                body = "\n\n".join(_block(child).text for child in item.children)
                task = (
                    "" if item.checked is None else ("[x]" if item.checked else "[ ]")
                )
                if task and not body.startswith((" ", "\t", "\n")):
                    task += " "
                lines = (task + body).split("\n")
                units.append(
                    marker
                    + lines[0]
                    + "".join("\n" + " " * len(marker) + line for line in lines[1:])
                )
            # Loose items preserve separate Paragraph children and nested lists.
            return _units(units, "\n\n")
        case Blockquote(children):
            units = [
                "\n".join("> " + line for line in _block(child).text.split("\n"))
                for child in children
            ]
            return _units(units, "\n>\n")
        case Table(header, rows):

            def row(cells: list[list[Inline]]) -> str:
                cells_text = " | ".join(_inlines(cell, table=True) for cell in cells)
                return "| " + cells_text + " |"

            table_header = (
                row(header) + "\n" + "| " + " | ".join("---" for _ in header) + " |"
            )
            rendered = _units([table_header, *(row(cells) for cells in rows)], "\n")
            rendered.table_header = table_header
            return rendered
    return _Rendered(text, [len(text)] if text else [])


class _Serializer:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.segments: list[SerializedSegment] = []
        self.runs: list[BodyRun] = []
        self.offset = 0

    def _append(self, text: str, path: list[str], source: SourceRange | None) -> None:
        if not text:
            return
        end = self.offset + len(text)
        copied_range = (
            SourceRange(source.start_line, source.end_line) if source else None
        )
        self.segments.append(
            SerializedSegment(self.offset, end, list(path), copied_range)
        )
        self.parts.append(text)
        self.offset = end

    def emit(self, text: str, path: list[str], source: SourceRange | None) -> int:
        if self.parts:
            self._append("\n\n", path, None)
        start = self.offset
        self._append(text, path, source)
        return start

    def body(
        self, children: list[Block | Section], path: list[str], levels: list[int]
    ) -> None:
        run: BodyRun | None = None
        for child in children:
            if isinstance(child, Section):
                run = None
                self.section(child, levels)
                continue
            rendered = _block(child)
            start = self.emit(rendered.text, path, child.source_range)
            block = SerializedBlock(
                start,
                self.offset,
                child,
                [start + end for end in rendered.boundaries],
                rendered.table_header,
            )
            if run is None:
                run = BodyRun(start, self.offset, list(path), list(levels), [])
                self.runs.append(run)
            run.blocks.append(block)
            run.end = self.offset

    def section(self, section: Section, parent_levels: list[int]) -> None:
        self.emit(
            "#" * section.level + " " + _escape(section.heading),
            section.heading_path,
            SourceRange(
                section.source_range.start_line, section.source_range.start_line
            ),
        )
        self.body(
            section.children, section.heading_path, [*parent_levels, section.level]
        )


def serialize_markdown(document: ParsedDocument) -> SerializedMarkdown:
    """Freeze canonical text/maps without mutating parser nodes or logging text.

    Empty direct ASTs have no synthetic title. Heading-only trees do retain
    outline text. Segments partition the complete canonical stream; runs select
    exactly the source-contiguous direct bodies eligible for heading-aware use.
    """
    _validate_tree(document)
    if not document.introduction and not document.sections:
        return SerializedMarkdown("", [], [])
    serializer = _Serializer()
    serializer.emit("# " + _escape(document.title), [document.title], None)
    serializer.body(list(document.introduction), [document.title], [1])
    for section in document.sections:
        serializer.section(section, [1])
    return SerializedMarkdown(
        "".join(serializer.parts), serializer.segments, serializer.runs
    )
