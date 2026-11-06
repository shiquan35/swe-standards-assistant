"""Offline search CLI contracts; no database or provider calls."""

import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.functions import search_handbook as cli


class SafeError(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__("PRIVATE api-key database-password")


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    result = SimpleNamespace(
        rank=1,
        similarity_score=0.892123,
        title="Code Review Standards",
        heading_paths=[["Pull Request Approval"]],
        file_path="engineering-handbook/code-review.md",
        source_spans=[[12, 20]],
        content="Pull requests must receive at least one approval...",
    )
    state = SimpleNamespace(
        result=result,
        session=object(),
        retrieval=SimpleNamespace(
            retrieve_chunks=Mock(return_value=[result]),
            RetrievalError=SafeError,
            EmbeddingError=SafeError,
        ),
    )
    state.acquire = Mock(return_value=nullcontext(state.session))
    monkeypatch.setattr(cli, "_get_retrieval", Mock(return_value=state.retrieval))
    monkeypatch.setattr(cli, "_session", state.acquire)
    return state


def test_requested_output(runtime, capsys) -> None:
    query = "What are the requirements for approving a pull request?"
    assert (
        cli.main(["--query", query, "--strategy", "heading_aware", "--top-k", "5"]) == 0
    )
    runtime.retrieval.retrieve_chunks.assert_called_once_with(
        session=runtime.session, question=query, strategy="heading_aware", top_k=5
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == (
        f"Query: {query}\nStrategy: heading_aware\nTop-K: 5\n\n"
        "Rank: 1\nSimilarity: 0.8921\nDocument: Code Review Standards\n"
        "Heading: Pull Request Approval\nSource: engineering-handbook/code-review.md\n"
        "Lines: 12-20\nContent:\nPull requests must receive at least one approval...\n"
    )


@pytest.mark.parametrize("strategy", ["fixed", "fixed_overlap", "heading_aware"])
def test_defaults_and_query_trimming(strategy, runtime, capsys) -> None:
    assert cli.main(["--query", "  Question 😀 漢字  ", "--strategy", strategy]) == 0
    runtime.retrieval.retrieve_chunks.assert_called_once_with(
        session=runtime.session, question="Question 😀 漢字", strategy=strategy, top_k=5
    )
    assert capsys.readouterr().out.startswith("Query: Question 😀 漢字\n")


def test_multiple_results_paths_and_spans(runtime, capsys) -> None:
    runtime.result.heading_paths = [["Handbook", "Approval"], ["Handbook", "Testing"]]
    runtime.result.source_spans = [[12, 20], [30, 32]]
    second = SimpleNamespace(**vars(runtime.result))
    second.rank = 2
    second.similarity_score = -0.125
    second.heading_paths = []
    second.source_spans = []
    second.content = "Unicode 😀\nSecond line"
    runtime.retrieval.retrieve_chunks.return_value = [runtime.result, second]
    assert cli.main(["--query", "Q", "--strategy", "fixed", "--top-k", "2"]) == 0
    output = capsys.readouterr().out
    assert "Heading: Handbook > Approval; Handbook > Testing\n" in output
    assert "Lines: 12-20, 30-32\n" in output
    assert "\n\nRank: 2\nSimilarity: -0.1250\n" in output
    assert "Heading: (none)\n" in output
    assert "Lines: (none)\nContent:\nUnicode 😀\nSecond line\n" in output


@pytest.mark.parametrize("top_k", [1, 100])
def test_top_k_boundaries(top_k, runtime) -> None:
    assert cli.main(["--query", "Q", "--strategy", "fixed", "--top-k", str(top_k)]) == 0
    assert runtime.retrieval.retrieve_chunks.call_args.kwargs["top_k"] == top_k


def test_empty_results_are_success(runtime, capsys) -> None:
    runtime.retrieval.retrieve_chunks.return_value = []
    assert cli.main(["--query", "Q", "--strategy", "fixed"]) == 0
    captured = capsys.readouterr()
    assert (
        captured.out
        == "Query: Q\nStrategy: fixed\nTop-K: 5\n\nNo matching chunks found.\n"
    )
    assert not captured.err


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--query", "Q"],
        ["--strategy", "fixed"],
        ["--query", "", "--strategy", "fixed"],
        ["--query", "  ", "--strategy", "fixed"],
        ["--query", "Q", "--strategy", "unknown"],
        *[
            ["--query", "Q", "--strategy", "fixed", "--top-k", value]
            for value in ("0", "-1", "101", "1.5", "text")
        ],
    ],
)
def test_invalid_args_do_not_load_runtime(args, monkeypatch, capsys) -> None:
    load = Mock(side_effect=AssertionError("Must not load runtime"))
    monkeypatch.setattr(cli, "_get_retrieval", load)
    with pytest.raises(SystemExit) as caught:
        cli.main(args)
    assert caught.value.code == 2
    load.assert_not_called()
    captured = capsys.readouterr()
    assert not captured.out
    assert "error:" in captured.err


@pytest.mark.parametrize("stage", ["import", "session", "search"])
@pytest.mark.parametrize(
    "failure,reason",
    [
        (RuntimeError("PRIVATE api-key database-password"), "search_failed"),
        (SafeError("database_error"), "database_error"),
        (SafeError("missing_api_key"), "missing_api_key"),
        (SafeError("PRIVATE"), "search_failed"),
    ],
)
def test_failures_are_safe_and_no_partial_output(
    stage, failure, reason, runtime, monkeypatch, capsys
) -> None:
    if stage == "import":
        monkeypatch.setattr(cli, "_get_retrieval", Mock(side_effect=failure))
        reason = "search_failed"
    elif stage == "session":
        runtime.acquire.side_effect = failure
    else:
        runtime.retrieval.retrieve_chunks.side_effect = failure
    assert cli.main(["--query", "PRIVATE QUERY", "--strategy", "fixed"]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert captured.err == f"Search failed: {reason}.\n"


def test_real_module_help_works_without_runtime() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "app.functions.search_handbook", "--help"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "--query" in completed.stdout
    assert "--strategy" in completed.stdout
    assert "--top-k" in completed.stdout
    assert not completed.stderr
