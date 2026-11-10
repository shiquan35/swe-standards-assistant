"""Offline CLI contracts: validation, lazy runtime, safe failures and publication."""

import copy
import json
import logging
import os
import subprocess
import sys
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.evaluation import retrieval
from app.functions import evaluate_retrieval as cli


@pytest.fixture
def harness(tmp_path, monkeypatch):
    handbook = tmp_path / "handbook"
    handbook.mkdir()
    (handbook / "policy.md").write_text("Require tests before merging.")
    dataset = tmp_path / "cases.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "id": "CASE-1",
                    "question": "What is required?",
                    "known_relevant_sources": ["policy.md"],
                    "expected_evidence": ["Require tests before merging."],
                    "answerable": True,
                    "category": "Direct Information Retrieval",
                }
            ]
        )
    )
    state = SimpleNamespace(
        dataset=dataset,
        output=tmp_path / "reports" / "report.json",
        calls=[],
        evaluations=[],
        failure=None,
        mutate=None,
    )

    @contextmanager
    def session():
        state.calls.append("session")
        try:
            yield "offline-session"
        finally:
            state.calls.append("session_closed")

    def evaluate(**kwargs):
        state.evaluations.append(kwargs)
        assert not state.output.exists() or kwargs["parameters"]["force"]
        if state.failure is not None:
            raise state.failure
        report = {
            "metadata": {"dataset_sha256": kwargs["dataset"].dataset_sha256},
            "experiments": [
                {
                    "configuration": {
                        "strategy": config.strategy,
                        "max_tokens": config.max_tokens,
                        "overlap_tokens": config.overlap_tokens,
                        "top_k": k,
                    },
                    "metrics": {
                        "evidence_hit_at_k": 1.0,
                        "macro_evidence_recall_at_k": 0.5,
                        "eligible_case_count": 1,
                    },
                    "cases": [],
                }
                for config in kwargs["configurations"]
                for k in kwargs["top_ks"]
            ],
        }
        if state.mutate is not None:
            state.mutate(report)
        return report

    evaluation = SimpleNamespace(
        DEFAULT_DATASET=dataset,
        load_dataset=partial(
            retrieval.load_dataset, handbook_root=handbook, repository_root=tmp_path
        ),
        expand_configurations=retrieval.expand_configurations,
        parse_run_ids=retrieval.parse_run_ids,
        evaluate_retrieval=evaluate,
    )
    state.api = evaluation
    monkeypatch.setattr(cli, "_get_evaluation", lambda: evaluation)
    monkeypatch.setattr(cli, "_session", session)
    monkeypatch.setattr(cli, "BACKEND_ROOT", tmp_path)
    return state


def test_help_subprocess_never_imports_runtime(tmp_path):
    backend = Path(__file__).resolve().parents[2]
    script = f"""
import importlib.abc
import runpy
import sys
sys.path.insert(0, {str(backend)!r})
class BlockRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('app.core', 'app.evaluation', 'app.ingestion', 'sqlmodel', 'openai')):
            raise AssertionError('Runtime import: ' + fullname)
sys.meta_path.insert(0, BlockRuntime())
sys.argv = ['evaluate_retrieval', '--help']
runpy.run_module('app.functions.evaluate_retrieval', run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for option in (
        "--strategy",
        "--max-tokens",
        "--overlap-tokens",
        "--top-k",
        "--dataset",
        "--output",
        "--run-id",
        "--force",
    ):
        assert option in result.stdout
    assert not list(tmp_path.iterdir())


def test_defaults_and_summary(harness, capsys, caplog):
    with caplog.at_level(logging.INFO, logger=cli.__name__):
        assert cli.main(["--output", str(harness.output)]) == 0
    kwargs = harness.evaluations[0]
    assert kwargs["session"] == "offline-session"
    assert [
        (c.strategy, c.max_tokens, c.overlap_tokens) for c in kwargs["configurations"]
    ] == [
        ("fixed", 200, 0),
        ("fixed_overlap", 200, 40),
        ("heading_aware", 200, 40),
    ]
    assert kwargs["top_ks"] == (3, 5)
    report = json.loads(harness.output.read_text())
    assert len(report["experiments"]) == 6
    assert harness.calls == ["session", "session_closed"]
    output = capsys.readouterr().out
    assert "6 experiment rows" in output
    assert "incomplete-ground-truth" in output.lower()
    assert "EvidenceHit@K=1.0" in output
    assert "Recall@K=0.5" in output
    assert "eligible_case_count=1" in output
    assert "No winner inferred" in output
    assert "evaluation_report_written" in caplog.text
    assert "What is required?" not in caplog.text
    assert list(harness.output.parent.iterdir()) == [harness.output]


@pytest.mark.parametrize("root_handler", [False, True])
def test_standalone_info_logging_without_duplicate_handlers(tmp_path, root_handler):
    backend = Path(__file__).resolve().parents[2]
    output = tmp_path / "report.json"
    script = f"""
import logging
import sys
from contextlib import nullcontext
from types import SimpleNamespace
sys.path.insert(0, {str(backend)!r})
from app.functions import evaluate_retrieval as cli
if {root_handler!r}:
    logging.basicConfig()
cli._get_evaluation = lambda: SimpleNamespace(
    DEFAULT_DATASET='unused',
    load_dataset=lambda path: SimpleNamespace(dataset_sha256='safe-dataset-hash'),
    expand_configurations=lambda *args: (('configuration',), (3,)),
    parse_run_ids=lambda *args: {{}},
    evaluate_retrieval=lambda **kwargs: {{'experiments': []}},
)
cli._session = lambda: nullcontext('offline-session')
for _ in range(2):
    assert cli.main(['--output', {str(output)!r}, '--force']) == 0
assert len(cli.logger.handlers) == {0 if root_handler else 1}
assert cli.logger.propagate
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr.count("evaluation_report_written") == 2
    assert result.stderr.count("dataset_sha256=safe-dataset-hash") == 2
    assert result.stderr.count("experiment_count=1") == 2
    assert result.stdout.count(f"Report: {output}") == 2


def test_repeated_values_replace_defaults_and_deduplicate(harness):
    first, second = uuid4(), uuid4()
    overrides = [f"fixed:100:0={first}", f"heading_aware:300:10={second}"]
    args = ["--dataset", str(harness.dataset), "--output", str(harness.output)]
    for flag, values in (
        ("--strategy", ["fixed", "heading_aware", "fixed"]),
        ("--max-tokens", ["100", "300", "100"]),
        ("--overlap-tokens", ["10", "20"]),
        ("--top-k", ["1", "8", "8"]),
        ("--run-id", overrides),
    ):
        for value in values:
            args.extend([flag, value])
    assert cli.main(args) == 0
    kwargs = harness.evaluations[0]
    assert len(kwargs["configurations"]) == 6
    assert kwargs["top_ks"] == (1, 8)
    assert kwargs["run_ids"] == {
        retrieval.Configuration("fixed", 100, 0): first,
        retrieval.Configuration("heading_aware", 300, 10): second,
    }
    assert kwargs["parameters"]["run_id"] == overrides
    assert kwargs["parameters"]["max_tokens"] == [100, 300, 100]
    assert len(json.loads(harness.output.read_text())["experiments"]) == 12


def test_all_input_validation_precedes_session(harness, monkeypatch):
    order = []
    for name in ("load_dataset", "expand_configurations", "parse_run_ids"):
        original = getattr(harness.api, name)

        def record(*args, _name=name, _original=original, **kwargs):
            assert not harness.calls
            order.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(harness.api, name, record)
    assert cli.main(["--output", str(harness.output)]) == 0
    assert order == ["load_dataset", "expand_configurations", "parse_run_ids"]


@pytest.mark.parametrize(
    "args",
    [
        ["--max-tokens", "0"],
        ["--max-tokens", "-1"],
        ["--overlap-tokens", "-1"],
        ["--overlap-tokens", "200"],
        ["--top-k", "0"],
        ["--top-k", "101"],
        ["--run-id", "bad"],
        ["--run-id", "fixed:100:0=not-a-uuid"],
    ],
)
def test_invalid_inputs_never_open_session(harness, args):
    assert cli.main([*args, "--output", str(harness.output)]) == 1
    assert harness.calls == []
    assert not harness.output.parent.exists()


@pytest.mark.parametrize(
    "flag,value",
    [("--strategy", "bad"), ("--top-k", "secret"), ("--unknown", "secret")],
)
def test_argparse_rejects_bad_arguments_without_runtime(monkeypatch, flag, value):
    def forbidden():
        pytest.fail("Runtime accessed for invalid arguments")

    monkeypatch.setattr(cli, "_get_evaluation", forbidden)
    with pytest.raises(SystemExit) as error:
        cli.main([flag, value])
    assert error.value.code == 2


def test_invalid_dataset_never_opens_session(harness, capsys):
    harness.dataset.write_text("secret invalid JSON")
    assert cli.main(["--output", str(harness.output)]) == 1
    assert harness.calls == []
    assert not harness.output.parent.exists()
    assert "invalid_dataset_json" in capsys.readouterr().err


def test_existing_destination_guard(harness):
    harness.output.parent.mkdir()
    harness.output.write_bytes(b"original")
    assert cli.main(["--output", str(harness.output)]) == 1
    assert harness.calls == []
    assert harness.output.read_bytes() == b"original"
    assert list(harness.output.parent.iterdir()) == [harness.output]


@pytest.mark.parametrize("kind", ["parent_file", "directory", "unwritable", "symlink"])
def test_invalid_output_precedes_session(harness, monkeypatch, kind):
    if kind == "parent_file":
        harness.output.parent.write_text("not a directory")
    else:
        harness.output.parent.mkdir()
        if kind == "directory":
            harness.output.mkdir()
        elif kind == "symlink":
            harness.output.symlink_to(harness.output.parent / "missing")
        else:
            monkeypatch.setattr(cli.os, "access", lambda *_args: False)
    assert cli.main(["--output", str(harness.output), "--force"]) == 1
    assert harness.calls == []


def test_runtime_failure_leaves_no_report(harness, capsys, caplog):
    harness.failure = RuntimeError("credentials=secret question SQL parameters")
    assert cli.main(["--output", str(harness.output)]) == 1
    assert list(harness.output.parent.iterdir()) == []
    assert harness.calls == ["session", "session_closed"]
    stderr = capsys.readouterr().err
    assert "evaluation_failed" in stderr
    assert "secret" not in stderr + caplog.text


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), object(), "\ud800"])
def test_serialization_failure_never_creates_temp(
    harness, monkeypatch, bad_value, capsys
):
    harness.mutate = lambda report: report["metadata"].update(bad=bad_value)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Temporary file created before serialization completed")

    monkeypatch.setattr(cli.tempfile, "NamedTemporaryFile", forbidden)
    assert cli.main(["--output", str(harness.output)]) == 1
    assert list(harness.output.parent.iterdir()) == []
    assert "serialization_failed" in capsys.readouterr().err


def test_force_replaces_only_after_complete_report(harness, monkeypatch):
    harness.output.parent.mkdir()
    harness.output.write_bytes(b"original")
    original_replace = cli.os.replace

    def replace(source, destination):
        assert harness.output.read_bytes() == b"original"
        assert Path(source).parent == harness.output.parent
        assert len(json.loads(Path(source).read_text())["experiments"]) == 6
        original_replace(source, destination)

    monkeypatch.setattr(cli.os, "replace", replace)
    assert cli.main(["--output", str(harness.output), "--force"]) == 0
    assert len(json.loads(harness.output.read_text())["experiments"]) == 6
    assert list(harness.output.parent.iterdir()) == [harness.output]


def test_force_failure_preserves_existing_report(harness):
    harness.output.parent.mkdir()
    harness.output.write_bytes(b"original")
    harness.failure = retrieval.EvaluationError("database_error")
    assert cli.main(["--output", str(harness.output), "--force"]) == 1
    assert harness.output.read_bytes() == b"original"


def test_default_filename_is_utc_timestamped_under_backend(harness):
    assert cli.main([]) == 0
    assert len(harness.evaluations) == 1
    paths = list((cli.BACKEND_ROOT / "evaluation-reports").iterdir())
    assert len(paths) == 1
    assert paths[0].name.startswith("retrieval-")
    assert paths[0].name.endswith("Z.json")
    assert json.loads(paths[0].read_text())["experiments"]


def test_no_clobber_race_and_temp_cleanup(harness, monkeypatch, capsys):
    original_link = cli.os.link

    def race(source, destination):
        assert Path(source).parent == harness.output.parent
        harness.output.write_bytes(b"racing writer")
        original_link(source, destination)

    monkeypatch.setattr(cli.os, "link", race)
    assert cli.main(["--output", str(harness.output)]) == 1
    assert harness.output.read_bytes() == b"racing writer"
    assert list(harness.output.parent.iterdir()) == [harness.output]
    assert "output_exists" in capsys.readouterr().err


def test_publication_error_cleans_temp(harness, monkeypatch):
    def fail(*_args):
        raise OSError("secret filesystem details")

    monkeypatch.setattr(cli.os, "link", fail)
    assert cli.main(["--output", str(harness.output)]) == 1
    assert list(harness.output.parent.iterdir()) == []


@pytest.mark.parametrize("force", [False, True], ids=["link", "replace"])
def test_cleanup_failure_after_publication_still_succeeds(
    harness, monkeypatch, capsys, caplog, force
):
    operation = "replace" if force else "link"
    original_publish = getattr(cli.os, operation)
    published = []

    def publish(source, destination):
        original_publish(source, destination)
        published.append(True)

    def fail_unlink(path, *, missing_ok=False):
        assert published and missing_ok
        raise OSError(f"secret cleanup content path={path}")

    monkeypatch.setattr(cli.os, operation, publish)
    monkeypatch.setattr(Path, "unlink", fail_unlink)
    args = ["--output", str(harness.output)]
    if force:
        harness.output.parent.mkdir()
        harness.output.write_bytes(b"original")
        args.append("--force")
    with caplog.at_level(logging.INFO, logger=cli.__name__):
        assert cli.main(args) == 0
    assert len(json.loads(harness.output.read_text())["experiments"]) == 6
    captured = capsys.readouterr()
    assert f"Report: {harness.output}" in captured.out
    assert "evaluation_failed" not in captured.err + caplog.text
    assert "evaluation_report_written" in caplog.text
    warnings = [
        record for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert warnings[0].getMessage() == "evaluation_report_cleanup_failed"
    assert warnings[0].exc_info is None
    assert "secret" not in captured.err + caplog.text
    assert str(harness.output.parent) not in warnings[0].getMessage()
    assert len(list(harness.output.parent.glob(".*.tmp"))) == (0 if force else 1)


@pytest.mark.parametrize("force", [False, True], ids=["link", "replace"])
@pytest.mark.parametrize(
    "error_type,reason",
    [(FileExistsError, "output_exists"), (OSError, "output_write_failed")],
)
def test_cleanup_failure_preserves_primary_publication_error(
    harness, monkeypatch, capsys, caplog, force, error_type, reason
):
    def fail_publish(*_args):
        raise error_type(f"secret publication content path={harness.output}")

    def fail_unlink(path, *, missing_ok=False):
        assert missing_ok
        raise OSError(f"secret cleanup content path={path}")

    monkeypatch.setattr(cli.os, "replace" if force else "link", fail_publish)
    monkeypatch.setattr(Path, "unlink", fail_unlink)
    args = ["--output", str(harness.output)]
    if force:
        harness.output.parent.mkdir()
        harness.output.write_bytes(b"original")
        args.append("--force")
    assert cli.main(args) == 1
    captured = capsys.readouterr()
    assert f"Evaluation failed: {reason}." in captured.err
    assert f"evaluation_failed reason_code={reason}" in caplog.text
    assert "evaluation_report_written" not in caplog.text
    assert "secret" not in captured.err + caplog.text
    assert str(harness.output.parent) not in captured.err + caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    if force:
        assert harness.output.read_bytes() == b"original"
    else:
        assert not harness.output.exists()


def test_summary_null_denominators(harness, capsys):
    def null_metrics(report):
        for experiment in report["experiments"]:
            experiment["metrics"].update(
                evidence_hit_at_k=None,
                macro_evidence_recall_at_k=None,
                eligible_case_count=0,
            )

    harness.mutate = null_metrics
    assert cli.main(["--output", str(harness.output)]) == 0
    output = capsys.readouterr().out
    assert "EvidenceHit@K=null" in output
    assert "Recall@K=null" in output
    assert "eligible_case_count=0" in output


def test_only_recognized_allowlisted_errors_are_exposed(harness, capsys):
    class UntrustedError(Exception):
        @property
        def reason_code(self):
            pytest.fail("Arbitrary reason_code was accessed")

    harness.failure = UntrustedError("secret")
    assert cli.main(["--output", str(harness.output)]) == 1
    assert "evaluation_failed" in capsys.readouterr().err
    harness.failure = retrieval.EvaluationError("secret")
    assert cli.main(["--output", str(harness.output)]) == 1
    assert "secret" not in capsys.readouterr().err
    harness.failure = retrieval.EvaluationError("source_snapshot_mismatch")
    assert cli.main(["--output", str(harness.output)]) == 1
    assert "source_snapshot_mismatch" in capsys.readouterr().err


@pytest.mark.parametrize(
    "module_name,class_name,reason",
    [
        ("app.ingestion.retrieval", "RetrievalError", "run_not_searchable"),
        ("app.ingestion.embeddings", "EmbeddingError", "missing_api_key"),
    ],
)
def test_known_runtime_error_classes_are_safe(
    monkeypatch, module_name, class_name, reason
):
    class KnownError(ValueError):
        def __init__(self, code):
            self.reason_code = code
            super().__init__("secret provider details")

    monkeypatch.setitem(
        sys.modules, module_name, SimpleNamespace(**{class_name: KnownError})
    )
    assert cli._safe_reason(KnownError(reason)) == reason
    assert cli._safe_reason(KnownError("secret")) == "evaluation_failed"


def test_report_round_trip_does_not_mutate_payload(harness):
    report = {"unicode": "Straße", "nested": [None, {"value": 0.5}]}
    original = copy.deepcopy(report)
    harness.output.parent.mkdir()
    cli._write_report(harness.output, report, force=False)
    assert json.loads(harness.output.read_text()) == report == original
