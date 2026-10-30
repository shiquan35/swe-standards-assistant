"""Inspection CLI contracts, including real module invocation and safe errors."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.functions import chunk_handbook, parse_handbook
from app.ingestion import (
    ChunkingConfig,
    ChunkingError,
    ChunkStrategy,
    ParsedDocument,
    TiktokenTokenizer,
    chunk_document,
    parse_markdown_file,
)

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def topic(tmp_path: Path) -> Path:
    path = tmp_path / "private-topic.md"
    path.write_text(
        "# Private title\n\nIntroduction 😀 漢字 e\u0301.\n\n"
        "## Rules\n\n" + "Keep <|endoftext|> literal. " * 24,
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("strategy", ["fixed", "fixed_overlap", "heading_aware"])
@pytest.mark.parametrize("override", [False, True])
def test_full_content_and_every_metadata_field(
    topic: Path,
    strategy: ChunkStrategy,
    override: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    maximum = 45 if override else 500
    overlap = (
        (0 if strategy == "fixed" else 8)
        if override
        else (0 if strategy == "fixed" else 100)
    )
    args = [str(topic), "--strategy", strategy]
    if override:
        args.extend(["--max-tokens", str(maximum), "--overlap-tokens", str(overlap)])
    expected = chunk_document(
        parse_markdown_file(topic), strategy, ChunkingConfig(maximum, overlap)
    )
    before = topic.read_bytes()
    assert chunk_handbook.main(args) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    expected_output = ""
    for candidate in expected:
        spans = [[span.start_line, span.end_line] for span in candidate.source_spans]
        expected_output += (
            f"Ordinal: {candidate.ordinal}\n"
            f"Strategy: {strategy}\n"
            f"Tokens: {len(TiktokenTokenizer().encode(candidate.content))}\n"
            f"Actual overlap tokens: {candidate.actual_overlap_tokens}\n"
            f"Source: {candidate.source_path}\n"
            f"Heading paths: {json.dumps(candidate.heading_paths, ensure_ascii=False)}\n"
            f"Source spans: {json.dumps(spans)}\n"
            f"Heading prefix omitted: {candidate.heading_prefix_omitted}\n"
            f"Content:\n{candidate.content}\n\n"
        )
    assert captured.out == expected_output
    assert topic.read_bytes() == before
    assert sorted(path.name for path in topic.parent.iterdir()) == [topic.name]


def test_default_path_matches_parse_handbook_and_default_profile(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Observe the existing CLI's actual default rather than duplicating its path.
    existing_parser = Mock(return_value=ParsedDocument("D", None, [], []))
    monkeypatch.setattr(parse_handbook, "parse_markdown_file", existing_parser)
    monkeypatch.setattr(sys, "argv", ["parse_handbook"])
    parse_handbook.main()
    capsys.readouterr()
    parse = Mock(return_value=ParsedDocument("D", None, [], []))
    chunk = Mock(return_value=[])
    monkeypatch.setattr(chunk_handbook, "parse_markdown_file", parse)
    monkeypatch.setattr(chunk_handbook, "chunk_document", chunk)
    assert chunk_handbook.main([]) == 0
    parse.assert_called_once_with(existing_parser.call_args.args[0])
    chunk.assert_called_once_with(
        parse.return_value, "heading_aware", ChunkingConfig(500, 100)
    )
    assert capsys.readouterr().out == "No chunk candidates produced.\n"


@pytest.mark.parametrize(
    "strategy,overlap", [("fixed", 0), ("fixed_overlap", 100), ("heading_aware", 100)]
)
def test_strategy_specific_default_overlap(
    strategy: ChunkStrategy, overlap: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = ParsedDocument("D", None, [], [])
    monkeypatch.setattr(
        chunk_handbook, "parse_markdown_file", Mock(return_value=document)
    )
    chunk = Mock(return_value=[])
    monkeypatch.setattr(chunk_handbook, "chunk_document", chunk)
    assert chunk_handbook.main(["--strategy", strategy]) == 0
    chunk.assert_called_once_with(document, strategy, ChunkingConfig(500, overlap))


@pytest.mark.parametrize(
    "options",
    [
        ["--strategy", "unknown"],
        ["--max-tokens", "no"],
        ["--overlap-tokens", "1.5"],
        ["--max-tokens", "0"],
        ["--max-tokens", "-1"],
        ["--overlap-tokens", "-1"],
        ["--overlap-tokens", "500"],
        ["--overlap-tokens", "501"],
        ["--strategy", "fixed", "--overlap-tokens", "1"],
        ["--max-tokens", "50"],
        ["--unknown-option"],
    ],
)
def test_invalid_arguments_exit_before_reading_source(
    options: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parse = Mock(side_effect=AssertionError("Source must not be read"))
    monkeypatch.setattr(chunk_handbook, "parse_markdown_file", parse)
    with pytest.raises(SystemExit) as caught:
        chunk_handbook.main(options)
    assert caught.value.code == 2
    parse.assert_not_called()
    captured = capsys.readouterr()
    assert not captured.out
    assert "error:" in captured.err


@pytest.mark.parametrize("strategy", ["fixed", "fixed_overlap", "heading_aware"])
def test_direct_empty_ast_is_success(
    strategy: ChunkStrategy,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        chunk_handbook,
        "parse_markdown_file",
        Mock(return_value=ParsedDocument("D", None, [], [])),
    )
    assert chunk_handbook.main(["--strategy", strategy]) == 0
    captured = capsys.readouterr()
    assert captured.out == "No chunk candidates produced.\n"
    assert not captured.err


def test_heading_only_file_is_successful_zero_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "heading-only.md"
    path.write_text("# D\n\n## Empty", encoding="utf-8")
    assert chunk_handbook.main([str(path)]) == 0
    assert capsys.readouterr().out == "No chunk candidates produced.\n"


@pytest.mark.parametrize(
    "source", ["", "not a valid handbook", "# Private title\n\n## Rules\n\n𠮷"]
)
def test_real_processing_failure_is_nonzero_and_content_free(
    source: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "secret-path.md"
    path.write_text(source, encoding="utf-8")
    args = [str(path)]
    if "𠮷" in source:
        args.extend(["--max-tokens", "1", "--overlap-tokens", "0"])
    assert chunk_handbook.main(args) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert captured.err.startswith("Chunking failed: ")
    assert str(path) not in captured.err
    assert "Private title" not in captured.err
    assert "𠮷" not in captured.err
    if "𠮷" in source:
        assert captured.err == "Chunking failed: token_budget_unrepresentable.\n"


@pytest.mark.parametrize(
    "failure",
    [
        OSError("private-path.md SECRET CONTENT"),
        RuntimeError("Private title SECRET CONTENT"),
        ChunkingError("invalid_unicode"),
        ChunkingError("SECRET CONTENT"),
    ],
)
@pytest.mark.parametrize("stage", ["parse", "chunk"])
def test_exception_messages_never_leak_or_print_partial_candidates(
    failure: Exception,
    stage: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parse = Mock(return_value=ParsedDocument("D", None, [], []))
    chunk = Mock(return_value=[])
    if stage == "parse":
        parse.side_effect = failure
    else:
        chunk.side_effect = failure
    monkeypatch.setattr(chunk_handbook, "parse_markdown_file", parse)
    monkeypatch.setattr(chunk_handbook, "chunk_document", chunk)
    assert chunk_handbook.main(["private-path.md"]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    expected = (
        "invalid_unicode"
        if isinstance(failure, ChunkingError)
        and failure.reason_code == "invalid_unicode"
        else "processing_failed"
    )
    assert captured.err == f"Chunking failed: {expected}.\n"


def test_prefix_omission_is_displayed(
    topic: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        chunk_handbook.main([str(topic), "--max-tokens", "4", "--overlap-tokens", "0"])
        == 0
    )
    assert "Heading prefix omitted: True\n" in capsys.readouterr().out


@pytest.mark.parametrize("strategy", ["fixed", "fixed_overlap", "heading_aware"])
def test_real_module_entry_point(strategy: str, topic: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.functions.chunk_handbook",
            str(topic),
            "--strategy",
            strategy,
        ],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert f"Strategy: {strategy}\n" in result.stdout
    assert "Ordinal: 0\n" in result.stdout
    assert "Content:\n" in result.stdout


def test_real_module_failure_exit_status_and_safe_missing_path(tmp_path: Path) -> None:
    path = tmp_path / "sensitive-missing-file.md"
    result = subprocess.run(
        [sys.executable, "-m", "app.functions.chunk_handbook", str(path)],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 1
    assert not result.stdout
    assert "processing_failed" in result.stderr
    assert str(path) not in result.stderr


def test_help(topic: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        chunk_handbook.main([str(topic), "--help"])
    assert caught.value.code == 0
    output = capsys.readouterr().out
    for option in (
        "path",
        "fixed",
        "fixed_overlap",
        "heading_aware",
        "--max-tokens",
        "--overlap-tokens",
    ):
        assert option in output
