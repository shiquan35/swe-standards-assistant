"""Recovery CLI delegates exclusively to the pipeline's locked operation."""

import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from app.functions import recover_ingestion_run as cli


class SafeIngestionError(Exception):
    def __init__(self, reason_code: str, run_id: UUID | None = None) -> None:
        self.reason_code = reason_code
        self.run_id = run_id
        super().__init__("PRIVATE SOURCE api-key vector=[1,2,3]")


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    state = SimpleNamespace(
        run_id=uuid4(),
        session=object(),
        logger=Mock(),
        pipeline=SimpleNamespace(
            recover_ingestion_run=Mock(),
            ingest_handbook=Mock(),
            IngestionError=SafeIngestionError,
        ),
    )
    state.acquire = Mock(return_value=nullcontext(state.session))
    monkeypatch.setattr(cli, "_get_pipeline", Mock(return_value=state.pipeline))
    monkeypatch.setattr(cli, "_get_logger", Mock(return_value=state.logger))
    monkeypatch.setattr(cli, "_session", state.acquire)
    return state


def test_confirmed_recovery_only_calls_locked_transition(
    runtime: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main([str(runtime.run_id), "--confirm"]) == 0
    runtime.pipeline.recover_ingestion_run.assert_called_once_with(
        runtime.session,
        runtime.run_id,
    )
    runtime.pipeline.ingest_handbook.assert_not_called()
    captured = capsys.readouterr()
    assert (
        captured.out == f"Recovery completed: run_id={runtime.run_id} status=failed\n"
    )
    assert not captured.err
    assert runtime.logger.info.call_count == 2


@pytest.mark.parametrize("options", [[], ["not-a-uuid", "--confirm"], ["--confirm"]])
def test_invalid_run_id_rejected_before_runtime(
    options: list[str],
    runtime: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(options)
    assert caught.value.code == 2
    runtime.acquire.assert_not_called()
    runtime.pipeline.recover_ingestion_run.assert_not_called()
    assert "error:" in capsys.readouterr().err


def test_confirmation_is_mandatory(
    runtime: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main([str(runtime.run_id)])
    assert caught.value.code == 2
    assert "--confirm" in capsys.readouterr().err
    runtime.acquire.assert_not_called()
    runtime.pipeline.recover_ingestion_run.assert_not_called()
    runtime.logger.info.assert_not_called()


@pytest.mark.parametrize("reason", ["run_not_found", "run_not_running"])
def test_missing_or_nonrunning_run_fails_safely(
    reason: str,
    runtime: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime.pipeline.recover_ingestion_run.side_effect = SafeIngestionError(
        reason, runtime.run_id
    )
    assert cli.main([str(runtime.run_id), "--confirm"]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert captured.err == f"Recovery failed: {reason}. run_id={runtime.run_id}\n"
    assert "PRIVATE" not in captured.err + str(runtime.logger.mock_calls)
    runtime.pipeline.ingest_handbook.assert_not_called()


@pytest.mark.parametrize(
    "stage", ["_get_pipeline", "_get_logger", "_session", "pipeline"]
)
def test_runtime_failure_is_content_free(
    stage: str,
    runtime: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    failure = RuntimeError("PRIVATE SOURCE api-key vector=[1,2,3]")
    if stage == "pipeline":
        runtime.pipeline.recover_ingestion_run.side_effect = failure
    else:
        monkeypatch.setattr(cli, stage, Mock(side_effect=failure))
    assert cli.main([str(runtime.run_id), "--confirm"]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert (
        captured.err == f"Recovery failed: recovery_failed. run_id={runtime.run_id}\n"
    )
    assert "PRIVATE" not in str(runtime.logger.mock_calls)
    runtime.pipeline.ingest_handbook.assert_not_called()


def test_module_help_never_initializes_runtime() -> None:
    script = (
        "import runpy, sys\n"
        "class BlockRuntime:\n"
        " def find_spec(self, fullname, path=None, target=None):\n"
        "  if fullname in {'app.core.env', 'app.core.db', 'app.core.logger', 'app.ingestion.pipeline'}:\n"
        "   raise AssertionError('runtime import during help')\n"
        "sys.meta_path.insert(0, BlockRuntime())\n"
        "sys.argv = ['recover_ingestion_run', '--help']\n"
        "runpy.run_module('app.functions.recover_ingestion_run', run_name='__main__')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--confirm" in result.stdout
