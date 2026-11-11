"""CLI tests use fake services/sessions: no settings, DB, or paid requests."""

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Literal
from uuid import UUID

import pytest

from app.functions import answer_handbook as cli
from app.rag.errors import RagError
from app.rag.models import Citation, Claim, RagResponse

FIRST = UUID(int=1)
SECOND = UUID(int=2)
RUN = UUID(int=3)


def make_response(
    status: Literal[
        "answered", "partial", "clarification_needed", "abstained"
    ] = "answered",
) -> RagResponse:
    claims = [
        Claim(text="Run tests.", citation_ids=[SECOND, FIRST]),
        Claim(text="Review changes.", citation_ids=[FIRST]),
    ]
    citations = [
        Citation(
            chunk_id=FIRST,
            title="Engineering Handbook",
            file_path="handbook/review.md",
            heading_paths=[["Engineering", "Reviews"], ["Checks"]],
            source_spans=[[2, 8], [12, 15]],
        ),
        Citation(
            chunk_id=SECOND,
            title=None,
            file_path="handbook/testing.md",
            heading_paths=[],
            source_spans=[],
        ),
    ]
    return RagResponse(
        status=status,
        claims=[] if status == "abstained" else claims,
        citations=[] if status == "abstained" else citations,
        ingestion_run_id=RUN,
        reason=(
            "I don't know based on the available handbook evidence."
            if status == "abstained"
            else None
        ),
        unanswered_parts=(
            ["Deployment cadence"]
            if status in {"partial", "clarification_needed"}
            else []
        ),
        clarifying_question=(
            "Which project?" if status == "clarification_needed" else None
        ),
    )


@pytest.fixture
def fake_runtime(monkeypatch):
    state = SimpleNamespace(
        response=make_response(), error=None, calls=[], entered=0, closed=0
    )
    session = object()

    @contextmanager
    def fake_session():
        state.entered += 1
        try:
            yield session
        finally:
            state.closed += 1

    def answer_question(**kwargs):
        state.calls.append(kwargs)
        assert kwargs["session"] is session
        if state.error is not None:
            raise state.error
        return state.response

    monkeypatch.setattr(cli, "_session", fake_session)
    monkeypatch.setattr(
        cli, "_get_service", lambda: SimpleNamespace(answer_question=answer_question)
    )
    return state


@pytest.mark.parametrize(
    "status", ["answered", "partial", "clarification_needed", "abstained"]
)
@pytest.mark.parametrize("json_mode", [False, True])
def test_content_outcomes_succeed(status, json_mode, fake_runtime, capsys):
    fake_runtime.response = make_response(status)
    args = ["  How should changes be reviewed?  "] + (["--json"] if json_mode else [])
    assert cli.main(args) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert fake_runtime.calls[0]["question"] == "How should changes be reviewed?"
    assert fake_runtime.entered == fake_runtime.closed == 1
    if json_mode:
        assert json.loads(captured.out) == fake_runtime.response.model_dump(mode="json")
        assert RagResponse.model_validate_json(captured.out) == fake_runtime.response
    else:
        assert f"Status: {status}" in captured.out
        assert f"Ingestion run: {RUN}" in captured.out
        if status != "abstained":
            assert "Run tests. [2] [1]" in captured.out
            assert "Review changes. [1]" in captured.out
            assert captured.out.count("[1] Title:") == 1
            assert "Title: Engineering Handbook" in captured.out
            assert "Path: handbook/review.md" in captured.out
            assert "Headings: Engineering > Reviews; Checks" in captured.out
            assert "Lines: 2-8, 12-15" in captured.out
            assert "[2] Title: (none)" in captured.out
            assert "Headings: (none)\nLines: (none)" in captured.out
        else:
            assert "Reason: I don't know" in captured.out
            assert "Sources:" not in captured.out
        if status in {"partial", "clarification_needed"}:
            assert "Unanswered parts:\n- Deployment cadence" in captured.out
        if status == "clarification_needed":
            assert "Clarifying question: Which project?" in captured.out


def test_clarification_without_claims(fake_runtime, capsys):
    fake_runtime.response = make_response("clarification_needed").model_copy(
        update={"claims": [], "citations": []}
    )
    assert cli.main(["Which checks?"]) == 0
    captured = capsys.readouterr()
    assert "Clarifying question: Which project?" in captured.out
    assert "Sources:" not in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize(
    "arguments",
    [[], [""], [" \n "], ["q", "secret-extra"], ["--secret=sk-private"], ["q", "--js"]],
)
def test_invalid_arguments_are_lazy_and_safe(arguments, json_mode, monkeypatch, capsys):
    def forbidden():
        pytest.fail("Invalid arguments must not import service or open a session")

    monkeypatch.setattr(cli, "_get_service", forbidden)
    monkeypatch.setattr(cli, "_session", forbidden)
    assert cli.main(arguments + (["--json"] if json_mode else [])) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "secret" not in captured.err
    if json_mode:
        assert json.loads(captured.err)["error"]["reason_code"] in {
            "invalid_arguments",
            "invalid_question",
        }
    else:
        assert captured.err.startswith("Handbook answer failed:")


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize(
    "reason",
    [
        "missing_snapshot",
        "run_not_searchable",
        "database_error",
        "embedding_failed",
        "missing_api_key",
        "configuration_failed",
        "context_budget_exceeded",
        "invalid_citation_source",
        "invalid_model_output",
        "model_refusal",
        "incomplete_output",
        "provider_context_limit",
        "provider_failed",
        "invalid_unicode",
        "rag_failed",
    ],
)
def test_operational_errors_are_mode_matched(reason, json_mode, fake_runtime, capsys):
    fake_runtime.error = RagError(reason)
    assert cli.main(["private question"] + (["--json"] if json_mode else [])) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "private question" not in captured.err
    assert fake_runtime.closed == 1
    if json_mode:
        assert json.loads(captured.err) == {
            "error": {"reason_code": reason, "message": str(RagError(reason))}
        }
    else:
        assert reason in captured.err


@pytest.mark.parametrize("phase", ["import", "session", "answer", "render"])
@pytest.mark.parametrize("json_mode", [False, True])
def test_unexpected_errors_never_expose_details(
    phase, json_mode, fake_runtime, monkeypatch, capsys
):
    def fail(*_args, **_kwargs):
        raise RuntimeError("sk-private postgresql://private prompt completion")

    if phase == "import":
        monkeypatch.setattr(cli, "_get_service", fail)
    elif phase == "session":
        monkeypatch.setattr(cli, "_session", fail)
    elif phase == "render":
        fake_runtime.response = SimpleNamespace(model_dump_json=fail)
        monkeypatch.setattr(cli, "_format_response", fail)
    else:
        fake_runtime.error = RuntimeError("sk-private prompt completion")
    assert cli.main(["private question"] + (["--json"] if json_mode else [])) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    for secret in (
        "sk-private",
        "postgresql",
        "prompt",
        "completion",
        "private question",
    ):
        assert secret not in captured.err
    if json_mode:
        assert json.loads(captured.err)["error"]["reason_code"] == "rag_failed"
    else:
        assert "rag_failed" in captured.err


def test_tampered_rag_error_is_resanitized(fake_runtime, capsys):
    error = RagError("provider_failed")
    error.reason_code = "sk-private"
    error.args = ("private provider response",)
    fake_runtime.error = error
    assert cli.main(["question", "--json"]) == 1
    assert json.loads(capsys.readouterr().err) == {
        "error": {"reason_code": "rag_failed", "message": str(RagError("rag_failed"))}
    }


@pytest.mark.parametrize(
    "arguments", [["--help"], ["--json", "--help"], [], ["--json"]]
)
def test_fresh_process_does_not_import_settings_or_database(arguments):
    # Install an import barrier before runpy, rather than relying on cached modules.
    code = """
import importlib.abc
import runpy
import sys
class Barrier(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'app.core.env', 'app.core.db', 'app.rag.service', 'openai'}:
            raise AssertionError('forbidden runtime import')
sys.meta_path.insert(0, Barrier())
sys.argv = ['answer_handbook', *sys.argv[1:]]
runpy.run_module('app.functions.answer_handbook', run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-c", code, *arguments],
        capture_output=True,
        text=True,
        check=False,
        env={
            key: value
            for key, value in os.environ.items()
            if key != "RUN_LIVE_RAG_TEST"
        },
    )
    assert result.returncode == (0 if "--help" in arguments else 2)
    assert "forbidden runtime import" not in result.stderr
    if "--help" in arguments:
        assert "question" in result.stdout and "--json" in result.stdout
        assert result.stderr == ""
    elif "--json" in arguments:
        assert json.loads(result.stderr)["error"]["reason_code"] == "invalid_arguments"
