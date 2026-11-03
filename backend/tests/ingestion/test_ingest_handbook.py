"""Offline CLI contracts; all runtime dependencies are injected."""

import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from app.functions import ingest_handbook as cli


class SafeIngestionError(Exception):
    def __init__(self, reason_code: str, run_id: UUID | None = None) -> None:
        self.reason_code = reason_code
        self.run_id = run_id
        super().__init__("PRIVATE SOURCE api-key vector=[1,2,3]")


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    result = SimpleNamespace(
        run_id=uuid4(),
        snapshot_fingerprint="a" * 64,
        skipped=False,
        document_count=12,
        chunk_count=46,
        reused_embeddings=8,
        generated_embeddings=38,
    )
    pipeline = SimpleNamespace(
        ingest_handbook=Mock(return_value=result),
        IngestionError=SafeIngestionError,
    )
    state = SimpleNamespace(
        pipeline=pipeline,
        result=result,
        session=object(),
        embedder=object(),
        logger=Mock(),
    )
    state.acquire = Mock(return_value=nullcontext(state.session))
    monkeypatch.setattr(cli, "_get_pipeline", Mock(return_value=pipeline))
    monkeypatch.setattr(cli, "_get_logger", Mock(return_value=state.logger))
    monkeypatch.setattr(cli, "_create_embedder", Mock(return_value=state.embedder))
    monkeypatch.setattr(cli, "_session", state.acquire)
    monkeypatch.setattr(
        cli,
        "_create_config",
        lambda maximum, overlap: SimpleNamespace(
            max_tokens=maximum,
            overlap_tokens=overlap,
        ),
    )
    return state


@pytest.mark.parametrize(
    "strategy,overlap",
    [("fixed", 0), ("fixed_overlap", 100), ("heading_aware", 100)],
)
def test_defaults_and_fixed_root(
    strategy: str,
    overlap: int,
    runtime: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--strategy", strategy]) == 0
    assert cli.DEFAULT_ROOT == (
        Path(cli.__file__).resolve().parents[2]
        / "knowledge_base"
        / "engineering-handbook"
    )
    runtime.pipeline.ingest_handbook.assert_called_once_with(
        session=runtime.session,
        source_root=cli.DEFAULT_ROOT,
        strategy=strategy,
        config=SimpleNamespace(max_tokens=500, overlap_tokens=overlap),
        embedder=runtime.embedder,
    )
    captured = capsys.readouterr()
    assert not captured.err
    for field in (
        str(runtime.result.run_id),
        "status=completed",
        "documents=12",
        "chunks=46",
        "reused_embeddings=8",
        "generated_embeddings=38",
    ):
        assert field in captured.out
    assert runtime.logger.info.call_count == 2


@pytest.mark.parametrize("strategy", ["fixed", "fixed_overlap", "heading_aware"])
def test_explicit_limits(strategy: str, runtime: SimpleNamespace) -> None:
    assert (
        cli.main(
            [
                "--strategy",
                strategy,
                "--max-tokens",
                "8192",
                "--overlap-tokens",
                "0",
            ]
        )
        == 0
    )
    config = runtime.pipeline.ingest_handbook.call_args.kwargs["config"]
    assert (config.max_tokens, config.overlap_tokens) == (8192, 0)


@pytest.mark.parametrize(
    "options",
    [
        [],
        ["--strategy", "unknown"],
        ["--strategy", "fixed", "--max-tokens", "0"],
        ["--strategy", "fixed", "--max-tokens", "-1"],
        ["--strategy", "fixed", "--max-tokens", "8193"],
        ["--strategy", "fixed", "--max-tokens", "text"],
        ["--strategy", "fixed", "--overlap-tokens", "1"],
        ["--strategy", "fixed", "--overlap-tokens", "-1"],
        ["--strategy", "fixed_overlap", "--overlap-tokens", "500"],
        ["--strategy", "heading_aware", "--overlap-tokens", "501"],
        ["--strategy", "heading_aware", "--overlap-tokens", "1.5"],
        ["--strategy", "heading_aware", "--max-tokens", "50"],
        ["--strategy", "fixed", "--source-root", "/arbitrary"],
    ],
)
def test_invalid_arguments_never_acquire_runtime(
    options: list[str],
    runtime: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(options)
    assert caught.value.code == 2
    runtime.acquire.assert_not_called()
    runtime.pipeline.ingest_handbook.assert_not_called()
    runtime.logger.info.assert_not_called()
    assert "error:" in capsys.readouterr().err


def test_completed_snapshot_is_successful_noop(
    runtime: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime.result.skipped = True
    runtime.result.generated_embeddings = 0
    assert cli.main(["--strategy", "fixed"]) == 0
    output = capsys.readouterr().out
    assert "status=skipped" in output
    assert "generated_embeddings=0" in output
    runtime.pipeline.ingest_handbook.assert_called_once()


@pytest.mark.parametrize(
    "reason", ["no_sources", "source_read_failed", "run_running", "embedding_failed"]
)
@pytest.mark.parametrize("has_run", [False, True])
def test_pipeline_failures_are_safe(
    reason: str,
    has_run: bool,
    runtime: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_id = runtime.result.run_id if has_run else None
    runtime.pipeline.ingest_handbook.side_effect = SafeIngestionError(reason, run_id)
    assert cli.main(["--strategy", "fixed"]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert reason in captured.err
    if has_run:
        assert str(run_id) in captured.err
    assert "PRIVATE" not in captured.err + str(runtime.logger.mock_calls)
    assert "api-key" not in captured.err + str(runtime.logger.mock_calls)


@pytest.mark.parametrize(
    "stage",
    [
        "_get_pipeline",
        "_get_logger",
        "_create_config",
        "_create_embedder",
        "_session",
        "pipeline",
    ],
)
def test_unexpected_errors_never_expose_exception(
    stage: str,
    runtime: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    failure = RuntimeError("PRIVATE SOURCE api-key vector=[1,2,3]")
    if stage == "pipeline":
        runtime.pipeline.ingest_handbook.side_effect = failure
    else:
        monkeypatch.setattr(cli, stage, Mock(side_effect=failure))
    assert cli.main(["--strategy", "fixed"]) == 1
    captured = capsys.readouterr()
    assert captured.err == "Ingestion failed: ingestion_failed.\n"
    assert not captured.out
    assert "PRIVATE" not in str(runtime.logger.mock_calls)


def test_module_help_does_not_import_environment_or_database() -> None:
    script = (
        "import runpy, sys\n"
        "class BlockRuntime:\n"
        " def find_spec(self, fullname, path=None, target=None):\n"
        "  if fullname in {'app.core.env', 'app.core.db', 'app.core.logger', 'app.ingestion.pipeline'}:\n"
        "   raise AssertionError('runtime import during help')\n"
        "sys.meta_path.insert(0, BlockRuntime())\n"
        "sys.argv = ['ingest_handbook', '--help']\n"
        "runpy.run_module('app.functions.ingest_handbook', run_name='__main__')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--strategy" in result.stdout
