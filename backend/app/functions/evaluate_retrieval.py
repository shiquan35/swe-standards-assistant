"""Compare retrieval snapshots using incomplete-ground-truth evidence coverage."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sqlmodel import Session

BACKEND_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)

_SAFE_REASONS = frozenset(
    "empty_configuration invalid_strategy invalid_max_tokens invalid_top_k "
    "invalid_overlap unsafe_source_path invalid_local_sources empty_local_sources "
    "invalid_dataset_array invalid_dataset_json invalid_dataset_schema "
    "invalid_dataset_string duplicate_case invalid_dataset_labels "
    "invalid_answerability_labels invalid_source_path evidence_not_in_listed_source "
    "invalid_run_mapping duplicate_run_mapping invalid_configuration "
    "run_missing_or_ambiguous invalid_run_sources source_snapshot_mismatch "
    "database_error invalid_embedding_response run_not_searchable "
    "invalid_chunk_metadata invalid_query_vector missing_api_key configuration_failed "
    "embedding_failed input_token_limit invalid_unicode tokenization_failed "
    "client_initialization_failed invalid_response response_count response_index "
    "response_dimensions response_vector invalid_input_sequence invalid_input_type "
    "empty_input empty_input_tokens request_timeout connection_failed quota_exceeded "
    "authentication_failed permission_denied model_unavailable rate_limited "
    "invalid_request provider_server_error request_failed output_exists "
    "invalid_output_path output_not_writable serialization_failed output_write_failed".split()
)


class EvaluationError(ValueError):
    """CLI-owned, content-free failure code."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _get_evaluation():
    # Dataset/config validation and --help must not initialize DB/env/provider.
    from app.evaluation import retrieval

    return retrieval


@contextmanager
def _session() -> Generator[Session]:
    from sqlmodel import Session

    from app.core.db import engine

    with Session(engine) as session:
        yield session


def _safe_reason(error: Exception) -> str:
    # Consult only already-loaded, known modules; never trust an arbitrary
    # exception's reason_code (or import runtime dependencies while failing).
    recognized = isinstance(error, EvaluationError)
    for module_name, class_name in (
        ("app.evaluation.retrieval", "EvaluationError"),
        ("app.ingestion.retrieval", "RetrievalError"),
        ("app.ingestion.embeddings", "EmbeddingError"),
    ):
        module = sys.modules.get(module_name)
        error_type = getattr(module, class_name, None)
        if isinstance(error_type, type) and isinstance(error, error_type):
            recognized = True
    if recognized:
        reason = getattr(error, "reason_code", None)
        if type(reason) is str and reason in _SAFE_REASONS:
            return reason
    return "evaluation_failed"


def _validate_output(path: Path, *, force: bool) -> None:
    if os.path.lexists(path):
        if not force:
            raise EvaluationError("output_exists")
        if path.is_dir() or path.is_symlink():
            raise EvaluationError("invalid_output_path")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.parent.is_dir():
            raise EvaluationError("invalid_output_path")
        if not os.access(path.parent, os.W_OK | os.X_OK):
            raise EvaluationError("output_not_writable")
    except OSError:
        raise EvaluationError("invalid_output_path") from None


def _write_report(path: Path, report: object, *, force: bool) -> None:
    # Serialize completely before opening even a temporary output file.
    try:
        payload = (
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError):
        raise EvaluationError("serialization_failed") from None
    temporary: Path | None = None
    published = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if force:
            os.replace(temporary, path)
        else:
            # Atomic no-clobber publication, including a destination created
            # after preflight. Both paths live on the same filesystem.
            os.link(temporary, path)
        published = True
    except FileExistsError:
        raise EvaluationError("output_exists") from None
    except OSError:
        raise EvaluationError("output_write_failed") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # Never mask a primary failure or report a published file as
                # failed. Cleanup diagnostics must not expose paths/content.
                if published:
                    logger.warning("evaluation_report_cleanup_failed")


def _format_summary(report: Mapping[str, object]) -> str:
    lines = ["Incomplete-ground-truth evidence coverage (not overall relevance):"]
    experiments = cast(Sequence[Mapping[str, object]], report["experiments"])
    for experiment in experiments:
        config = cast(Mapping[str, object], experiment["configuration"])
        metrics = cast(Mapping[str, object], experiment["metrics"])
        hit = metrics["evidence_hit_at_k"]
        recall = metrics["macro_evidence_recall_at_k"]
        lines.append(
            f"{config['strategy']} max_tokens={config['max_tokens']} "
            f"overlap_tokens={config['overlap_tokens']} top_k={config['top_k']}: "
            f"EvidenceHit@K={hit if hit is not None else 'null'} "
            f"macro evidence Recall@K={recall if recall is not None else 'null'} "
            f"eligible_case_count={metrics['eligible_case_count']}"
        )
    lines.append(
        "Human relevance Hit@K/MRR unavailable; diagnostics are separate. No winner inferred."
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Validate inputs, evaluate once, and publish only a complete JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strategy",
        action="append",
        choices=("fixed", "fixed_overlap", "heading_aware"),
    )
    parser.add_argument("--max-tokens", action="append", type=int)
    parser.add_argument("--overlap-tokens", action="append", type=int)
    parser.add_argument("--top-k", action="append", type=int)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--run-id", action="append", default=[], metavar="STRATEGY:MAX:OVERLAP=UUID"
    )
    parser.add_argument(
        "--force", action="store_true", help="Atomically replace an existing report."
    )
    args = parser.parse_args(argv)
    # Keep --help free of runtime imports and retain propagation for callers
    # that already capture/configure stdlib logging (including pytest).
    logger.setLevel(logging.INFO)
    if not logger.hasHandlers():
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(handler)
    try:
        evaluation = _get_evaluation()
        dataset_path = (
            args.dataset if args.dataset is not None else evaluation.DEFAULT_DATASET
        )
        dataset = evaluation.load_dataset(dataset_path)
        strategies = (
            args.strategy
            if args.strategy is not None
            else ["fixed", "fixed_overlap", "heading_aware"]
        )
        max_tokens = args.max_tokens if args.max_tokens is not None else [200]
        overlap_tokens = (
            args.overlap_tokens if args.overlap_tokens is not None else [40]
        )
        top_k = args.top_k if args.top_k is not None else [3, 5]
        configurations, top_ks = evaluation.expand_configurations(
            strategies, max_tokens, overlap_tokens, top_k
        )
        run_ids = evaluation.parse_run_ids(args.run_id, configurations)
        output = (
            args.output
            if args.output is not None
            else (
                BACKEND_ROOT
                / "evaluation-reports"
                / f"retrieval-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.json"
            )
        )
        _validate_output(output, force=args.force)
        parameters = {
            "strategy": strategies,
            "max_tokens": max_tokens,
            "overlap_tokens": overlap_tokens,
            "top_k": top_k,
            "dataset": str(dataset_path),
            "output": str(output),
            "run_id": list(args.run_id),
            "force": args.force,
        }
        print(
            f"Evaluating {len(configurations) * len(top_ks)} experiment rows."
        )  # noqa: T201
        with _session() as session:
            report = evaluation.evaluate_retrieval(
                session=session,
                dataset=dataset,
                configurations=configurations,
                top_ks=top_ks,
                run_ids=run_ids,
                parameters=parameters,
            )
        summary = _format_summary(report)
        _write_report(output, report, force=args.force)
    except Exception as error:
        reason = _safe_reason(error)
        logger.error("evaluation_failed reason_code=%s", reason)
        print(f"Evaluation failed: {reason}.", file=sys.stderr)  # noqa: T201
        return 1

    logger.info(
        "evaluation_report_written output=%s dataset_sha256=%s experiment_count=%s",
        output,
        dataset.dataset_sha256,
        len(configurations) * len(top_ks),
    )
    print(f"{summary}\nReport: {output}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
