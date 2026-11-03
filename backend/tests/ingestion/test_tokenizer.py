"""Literal full-string tokenization and runtime contract validation."""

from dataclasses import asdict

import pytest
import tiktoken

from app.ingestion import (
    ChunkCandidate,
    ChunkingConfig,
    ChunkingError,
    ChunkPart,
    TiktokenTokenizer,
    Tokenizer,
)


@pytest.mark.parametrize(
    "text", ["", "hello world", "😀漢字e\u0301\n\t ", "<|endoftext|><|fim_prefix|>"]
)
def test_exact_literal_full_string_encoding(text: str) -> None:
    concrete = TiktokenTokenizer()
    tokenizer: Tokenizer = concrete
    expected = tiktoken.get_encoding("cl100k_base").encode(text, disallowed_special=())
    assert tokenizer.encode(text) == expected
    assert concrete.count(text) == len(expected)
    assert tiktoken.get_encoding("cl100k_base").decode(expected) == text


@pytest.mark.parametrize(
    "text", ["\ud800", "\udfff", "before\ud800after", "\ud83d\ude00"]
)
def test_surrogates_never_replaced(text: str) -> None:
    with pytest.raises(ChunkingError, match="^invalid_unicode$"):
        TiktokenTokenizer().encode(text)


def test_count_reencodes_complete_string() -> None:
    tokenizer = TiktokenTokenizer()
    assert tokenizer.count("hello") != tokenizer.count("hel") + tokenizer.count("lo")


@pytest.mark.parametrize(
    "maximum, overlap",
    [
        (0, 0),
        (-1, 0),
        (1, -1),
        (10, 10),
        (10, 11),
        (True, 0),
        (10, False),
        (10.5, 0),
        (10, 1.5),
        ("10", 0),
        (10, None),
    ],
)
def test_config_rejects_invalid_runtime_types(maximum: object, overlap: object) -> None:
    with pytest.raises(ValueError):
        ChunkingConfig(maximum, overlap)  # type: ignore[arg-type]


def test_config_defaults_and_dataclass_contracts() -> None:
    assert asdict(ChunkingConfig()) == {"max_tokens": 500, "overlap_tokens": 100}
    assert ChunkingConfig(1, 0).max_tokens == 1
    source = ChunkPart(0, 3, "source", 10, 13)
    context = ChunkPart(3, 5, "context", context_kind="markdown_wrapper")
    candidate = ChunkCandidate(0, "fixed", "abc!!", 2, parts=[source, context])
    assert candidate.parts[0].canonical_start == 10
    assert candidate.parts[1].canonical_start is None
    assert candidate.actual_overlap_tokens == 0
    assert candidate.heading_prefix_omitted is False
    candidate.heading_paths.append(["one"])
    other = ChunkCandidate(1, "heading_aware", "abc", 1)
    assert other.heading_paths == []
    assert other.parts == []
