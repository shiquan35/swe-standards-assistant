"""Fence a stale running ingestion run; never starts or retries ingestion."""

import argparse
import sys
from collections.abc import Sequence
from uuid import UUID, uuid4

from app.functions.ingest_handbook import _get_logger, _get_pipeline, _session


def main(argv: Sequence[str] | None = None) -> int:
    """Require explicit confirmation before delegating the locked transition."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=UUID)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm that the specified running worker should be fenced.",
    )
    args = parser.parse_args(argv)
    if not args.confirm:
        parser.error("recovery requires explicit --confirm")

    run_id: UUID = args.run_id
    invocation_id = uuid4()
    pipeline = None
    logger = None
    try:
        pipeline = _get_pipeline()
        logger = _get_logger()
        logger.info(
            "Recovery started invocation_id={} run_id={}",
            invocation_id,
            run_id,
        )
        with _session() as session:
            pipeline.recover_ingestion_run(session, run_id)
    except Exception as error:
        reason = "recovery_failed"
        if pipeline is not None and isinstance(error, pipeline.IngestionError):
            reason = error.reason_code
        if logger is not None:
            logger.error(
                "Recovery failed invocation_id={} run_id={} reason={}",
                invocation_id,
                run_id,
                reason,
            )
        print(  # noqa: T201
            f"Recovery failed: {reason}. run_id={run_id}",
            file=sys.stderr,
        )
        return 1

    logger.info(
        "Recovery finished invocation_id={} run_id={} status=failed",
        invocation_id,
        run_id,
    )
    print(f"Recovery completed: run_id={run_id} status=failed")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
