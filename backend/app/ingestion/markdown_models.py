"""Parser-owned source nodes, independent of persistence and Markdown libraries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SourceRange:
    """One-based, inclusive logical source lines."""

    start_line: int
    end_line: int


@dataclass
class Text:
    content: str
    kind: Literal["text"] = field(default="text", init=False)


@dataclass
class Emphasis:
    children: list[Inline]
    kind: Literal["emphasis"] = field(default="emphasis", init=False)


@dataclass
class Strong:
    children: list[Inline]
    kind: Literal["strong"] = field(default="strong", init=False)


@dataclass
class Strikethrough:
    children: list[Inline]
    kind: Literal["strikethrough"] = field(default="strikethrough", init=False)


@dataclass
class CodeSpan:
    content: str
    kind: Literal["code_span"] = field(default="code_span", init=False)


@dataclass
class Link:
    destination: str
    children: list[Inline]
    kind: Literal["link"] = field(default="link", init=False)


@dataclass
class Image:
    destination: str
    alt_text: str
    kind: Literal["image"] = field(default="image", init=False)


@dataclass
class SoftBreak:
    kind: Literal["soft_break"] = field(default="soft_break", init=False)


@dataclass
class HardBreak:
    kind: Literal["hard_break"] = field(default="hard_break", init=False)


@dataclass
class RawHTMLInline:
    content: str
    kind: Literal["raw_html_inline"] = field(default="raw_html_inline", init=False)


type Inline = (
    Text
    | Emphasis
    | Strong
    | Strikethrough
    | CodeSpan
    | Link
    | Image
    | SoftBreak
    | HardBreak
    | RawHTMLInline
)


@dataclass
class Paragraph:
    children: list[Inline]
    source_range: SourceRange
    kind: Literal["paragraph"] = field(default="paragraph", init=False)


@dataclass
class ListItem:
    children: list[Block]
    source_range: SourceRange
    checked: bool | None = None
    kind: Literal["list_item"] = field(default="list_item", init=False)


@dataclass
class ListBlock:
    ordered: bool
    start: int
    items: list[ListItem]
    source_range: SourceRange
    kind: Literal["list"] = field(default="list", init=False)


@dataclass
class CodeBlock:
    content: str
    language: str | None
    source_range: SourceRange
    kind: Literal["code_block"] = field(default="code_block", init=False)


@dataclass
class Table:
    header: list[list[Inline]]
    rows: list[list[list[Inline]]]
    source_range: SourceRange
    kind: Literal["table"] = field(default="table", init=False)


@dataclass
class Blockquote:
    children: list[Block]
    source_range: SourceRange
    kind: Literal["blockquote"] = field(default="blockquote", init=False)


@dataclass
class ThematicBreak:
    source_range: SourceRange
    kind: Literal["thematic_break"] = field(default="thematic_break", init=False)


@dataclass
class RawHTMLBlock:
    content: str
    source_range: SourceRange
    kind: Literal["raw_html_block"] = field(default="raw_html_block", init=False)


@dataclass
class HeadingBlock:
    """A heading inside a list/quote, not part of the document outline."""

    level: int
    children: list[Inline]
    source_range: SourceRange
    kind: Literal["heading"] = field(default="heading", init=False)


type Block = (
    Paragraph
    | ListBlock
    | CodeBlock
    | Table
    | Blockquote
    | ThematicBreak
    | RawHTMLBlock
    | HeadingBlock
)


@dataclass
class Section:
    heading: str
    level: int
    heading_path: list[str]
    source_range: SourceRange
    children: list[Block | Section] = field(default_factory=list)


@dataclass
class ParsedDocument:
    title: str
    source_path: str | None
    introduction: list[Block]
    sections: list[Section]
