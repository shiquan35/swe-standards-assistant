# Python Markdown libraries: verified capability facts

**Research date:** 2026-10-29  
**Purpose:** Factual comparison for design grilling, against the settled requirements below. This is not a library selection or recommendation.

## Requirements used as comparison axes

- GitHub Flavored Markdown (GFM) constructs: tables, strikethrough, task lists, autolinks, fenced code, and raw HTML.
- A traversable structured representation that retains inline links, emphasis, and images, plus nested blockquotes and lists.
- Source line spans for section/block nodes.
- Parse directly from a Markdown text string.
- Unsupported/unconfigured extension syntax should not make otherwise parseable input fail; the observed fallback behavior matters.

GFM comprises CommonMark plus its documented extensions; raw HTML is part of the CommonMark base. See the [GFM specification](https://github.github.com/gfm/) and [CommonMark specification](https://spec.commonmark.org/).

## Comparison

| Library | GFM-related facts | Structured representation | Source positions | Parse from text / unsupported syntax |
|---|---|---|---|---|
| **markdown-it-py** | Its `gfm-like` preset is explicitly described as *approximately* GFM and enables tables, strikethrough, and linkify; it requires `linkify-it-py`. `gfm-like2` adds task lists, alerts, and single-tilde strikethrough. The project docs also expose these features as individual plugins. CommonMark is a separate preset. Raw HTML is governed by the parser's `html` option/preset, rather than being one of the listed GFM plugins. | `parse(text)` returns block tokens; inline tokens are nested under an `inline` token's `children`. Links, images, emphasis, and other inline constructs are distinct token types. Block nesting is represented by paired open/close tokens and levels; `SyntaxTreeNode` can collapse these into traversable children. | Block tokens expose `map` as a source-line range (examples show `[start, end]`, with zero-based, end-exclusive line indices). Inline child tokens in the documented examples have `map=None`; line spans are therefore block-token-level, not a per-inline-node feature. | `MarkdownIt.parse(src)` accepts a string directly. The docs demonstrate disabling a rule and show the unrecognized Markdown characters retained as text; adding custom syntax is supported through plugins/rules. |
| **Mistune** | Built-in plugins include tables, strikethrough, task lists, and URL autolinking. The URL plugin is not enabled by default by `create_markdown`; task lists are also opt-in. The legacy `mistune.html()` helper enables strikethrough, tables, and footnotes by default, but not task lists or URL autolinking. The documented URL plugin handles raw URLs; GFM-like exactness for every autolink case is not asserted by those plugin docs. Fenced code and raw HTML are supported by the parser; raw-HTML escaping depends on renderer configuration. | `renderer='ast'` (or `renderer=None`) returns nested dictionaries/lists. Docs enumerate distinct inline tokens including text, emphasis, strong, inline HTML, links and images, and block tokens including blockquotes, lists, and list items. | The documented AST token schema does not list a source span or line map. The parser state internally has a cursor, but the public AST documentation does not specify a supported source-position field. | Markdown instances accept source text as a string. The official example shows `~~s~~` remaining literal when the strikethrough plugin is not configured, and parsed as strikethrough when enabled. `create_markdown()` escapes raw HTML by default; `escape=False` leaves it unescaped. |
| **Marko** | Provides a built-in `gfm` Markdown subclass. Its implementation registers task-list paragraphs, strikethrough, bare-URL autolinks, tables, and GFM alert blocks; core parsing provides fenced code, HTML, and CommonMark autolinks. The extension docs identify it as GFM, while the implementation's concrete registered elements are the exact listed feature evidence here. | `Markdown.parse(text)` returns a document AST of element objects. The API has block and inline element classes; links, images, emphasis, strong emphasis, inline HTML, quotes, and lists have distinct element types/children. | Elements expose `source_span` as `(start, end)` character offsets into **normalized** source; line terminators are normalized to `\n` and NUL is replaced, so offsets can differ from original CRLF/CR input. The usage guide says extension-produced elements may have `None` positions if they do not record them. `syntax_spans` separately marks syntax-only regions for inline nodes. Converting offsets to line numbers requires mapping against the same normalized source. | Both `Markdown.parse(text)` and `Parser.parse(text)` accept a string. Core inline `RawText` is documented as the fallback for unmatched text. Marko's GFM HTML renderer applies a tag filter to raw HTML; the normal renderer's raw-HTML/security behavior is configurable/documented separately. |
| **Python-Markdown** | Included `Extra` bundles tables and fenced code (among other PHP Markdown Extra-like extensions). The official included-extension list does not list GFM strikethrough, task lists, or bare-URL autolinking as built-ins; third-party/custom extensions are supported. Its fenced-code extension documentation says fenced code is root-level only, not nested in lists or blockquotes. | Parsing builds an `xml.etree.ElementTree` representation via block processors and tree processors, with inline processors adding element nodes for markup. This is a traversable tree, but raw HTML can be stashed and restored rather than represented as ordinary Markdown AST nodes. | The documented ElementTree/API does not provide source line spans on block nodes. Its preprocessors can transform source lines before parsing, which is an additional consideration for any externally reconstructed positions. | `markdown.markdown(text)` and `Markdown.convert(source)` accept Unicode Markdown strings. The parser's extension API allows custom preprocessing/block/tree/inline/postprocessing; the docs do not specify a general source-position facility. Python-Markdown explicitly warns its HTML output is not sanitized. |

## Evidence and qualifications by library

### markdown-it-py

- [Using markdown-it-py](https://markdown-it-py.readthedocs.io/en/latest/using.html): parser presets; `parse()`; token examples and `map`; nested inline children; syntax-tree conversion; rule enabling/disabling. The page labels `gfm-like` approximate GFM and lists the `gfm-like2` additions.
- [Plugin extensions](https://markdown-it-py.readthedocs.io/en/latest/plugins.html): core-embedded table, strikethrough, task-list, and alert features; preset summaries; other extensions via `mdit-py-plugins`.
- [Design principles](https://markdown-it-py.readthedocs.io/en/latest/architecture.html): describes flat token sequence, paired block open/close tokens, nested inline tokens, and AST conversion as an option.
- [Token source](https://github.com/executablebooks/markdown-it-py/blob/master/markdown_it/token.py): token fields including `map`, `children`, `type`, and nesting metadata.
- [Parser source](https://github.com/executablebooks/markdown-it-py/blob/master/markdown_it/main.py): `MarkdownIt.parse(src: str)` signature and string validation.

### Mistune

- [Built-in plugins](https://mistune.lepture.com/en/latest/plugins.html): explicit enablement and behavior for tables, strikethrough, task lists, and raw URL linking; distinguishes defaults of `mistune.html()` from explicit plugin configuration.
- [How to Use Mistune](https://mistune.lepture.com/en/latest/guide.html): `create_markdown()` defaults, text input, escaping options, and AST mode. Includes the literal `~~s~~` example with no plugin.
- [Parsing AST tokens](https://mistune.lepture.com/en/latest/advanced.html#parsing-ast-tokens): nested token dictionary structure and documented inline/block/list token kinds.
- [API Reference](https://mistune.lepture.com/en/latest/api.html): `create_markdown`, renderer and parser APIs, and built-in plugin API.
- [Mistune core source](https://github.com/lepture/mistune/blob/main/src/mistune/core.py): parser state has source text/cursor; token storage is dictionaries. This is implementation evidence, not a public source-map contract.

### Marko

- [Built-in extensions](https://marko-py.readthedocs.io/en/latest/extensions.html): built-in GFM extension API.
- [GFM extension source](https://github.com/frostming/marko/blob/master/marko/ext/gfm/__init__.py): exact extension element registrations.
- [GFM element source](https://github.com/frostming/marko/blob/master/marko/ext/gfm/elements.py): task-list paragraph detection, strikethrough, URL, table and alert element implementations.
- [Usage guide: AST and source positions](https://marko-py.readthedocs.io/en/latest/usage.html#source-positions): `parse()` AST, `source_span`, `syntax_spans`, normalized-input caveat, and possibility of missing positions on extension-produced nodes.
- [API reference](https://marko-py.readthedocs.io/en/latest/api.html): string-based parse methods, block/inline element types and element-position properties.
- [GFM renderer source](https://github.com/frostming/marko/blob/master/marko/ext/gfm/renderer.py): GFM rendering behavior for raw HTML (tag filtering), task-list markup, strikethrough, tables and URLs.

### Python-Markdown

- [Included extensions](https://python-markdown.github.io/extensions/): official built-in extension list and maintenance status.
- [Extra extension](https://python-markdown.github.io/extensions/extra/): explicitly lists tables and fenced code among its bundled extensions.
- [Fenced Code Blocks](https://python-markdown.github.io/extensions/fenced_code_blocks/): syntax and explicit root-level-only limitation.
- [Tables](https://python-markdown.github.io/extensions/tables/): table extension syntax and enablement.
- [Extension API](https://python-markdown.github.io/extensions/api/): processing stages and construction/manipulation of ElementTree; preprocessors receive and may modify source lines.
- [Library usage](https://python-markdown.github.io/library/): text-string API and warning that HTML output is not sanitized.
- [Core source](https://github.com/Python-Markdown/markdown/blob/master/markdown/core.py): `Markdown.convert(source)` and preprocessing, block parsing to ElementTree, tree processing and serialization pipeline.

## Open capabilities / matters not settled by these facts

1. Whether “GFM” means GitHub's full current behavior or only the specified subset. In particular, the `markdown-it-py` preset calls itself approximate, and Mistune describes individual plugins rather than a single full-GFM mode.
2. Whether GFM task-list syntax, URL autolink literals, raw HTML handling, and invalid table/HTML edge cases must match GitHub exactly. The presence of a feature/plugin name alone does not establish full spec conformance.
3. Whether a required “source line span” can be computed from block offsets or must be a first-class, line-based field on every target node. Marko uses character offsets; markdown-it-py exposes block-line maps; Mistune and Python-Markdown document no public block source map.
4. Whether source positions must include nested blockquote/list child nodes and inline nodes, and whether normalized-source offsets are acceptable.
5. What “tolerant unsupported extensions” means operationally: preserving unknown syntax as text, ignoring a feature that is not enabled, or tolerating a named but unavailable plugin. The sources establish literal fallback examples for disabled syntax in markdown-it-py and Mistune, and a raw-text fallback in Marko; they do not establish that an unavailable plugin name is silently accepted.
6. Whether raw HTML is to be preserved, escaped, filtered, or sanitized. These are separate behaviors from parsing HTML into a structured node, and differ by configuration/library.
