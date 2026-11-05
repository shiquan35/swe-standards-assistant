"""Publish an idempotent handbook snapshot with an explicit chunking strategy."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from loguru import Logger
    from sqlmodel import Session

    from app.ingestion.chunk_models import ChunkingConfig, ChunkStrategy
    from app.ingestion.embeddings import EmbeddingService

# Keep CLI validation independent of the ingestion package's eager exports.
EMBEDDING_MODEL = "text-embedding-3-small"
MAX_INPUT_TOKENS = 8192
DEFAULT_ROOT = (
    Path(__file__).resolve().parents[2] / "knowledge_base" / "engineering-handbook"
)


def _get_pipeline():
    # Keep module import, --help and argument validation independent of DB/env.
    from app.ingestion import pipeline

    return pipeline


def _get_logger() -> Logger:
    from app.core.logger import app_logger

    return app_logger


@contextmanager
def _session() -> Generator[Session]:
    from sqlmodel import Session

    from app.core.db import engine

    with Session(engine) as session:
        yield session


def _create_embedder() -> EmbeddingService:
    from app.core.env import env
    from app.ingestion.embeddings import EmbeddingService

    if env.OPENAI_EMBEDDING_MODEL != EMBEDDING_MODEL:
        raise ValueError("unsupported_embedding_model")
    return EmbeddingService(api_key=env.OPENAI_API_KEY)


def _create_config(max_tokens: int, overlap_tokens: int) -> ChunkingConfig:
    from app.ingestion.chunk_models import ChunkingConfig

    return ChunkingConfig(max_tokens, overlap_tokens)


def main(argv: Sequence[str] | None = None) -> int:
    """Return zero for publication/no-op, one for a safe runtime failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strategy",
        required=True,
        choices=("fixed", "fixed_overlap", "heading_aware"),
    )
    parser.add_argument("--max-tokens", type=int, default=200)
    parser.add_argument(
        "--overlap-tokens",
        type=int,
        default=None,
        help="Overlap target (default: 0 for fixed, 40 otherwise).",
    )
    args = parser.parse_args(argv)
    strategy: ChunkStrategy = args.strategy
    overlap = args.overlap_tokens
    if overlap is None:
        overlap = 0 if strategy == "fixed" else 40
    if args.max_tokens <= 0 or overlap < 0 or overlap >= args.max_tokens:
        parser.error("invalid token budget configuration")
    if args.max_tokens > MAX_INPUT_TOKENS:
        parser.error("max tokens must not exceed 8192")
    if strategy == "fixed" and overlap != 0:
        parser.error("fixed strategy requires zero overlap")

    invocation_id = uuid4()
    pipeline = None
    logger = None
    try:
        pipeline = _get_pipeline()
        logger = _get_logger()
        config = _create_config(args.max_tokens, overlap)
        logger.info(
            "CLI started invocation_id={} source_root={} strategy={} "
            "max_tokens={} overlap_tokens={} model={}",
            invocation_id,
            "knowledge_base/engineering-handbook",
            strategy,
            config.max_tokens,
            config.overlap_tokens,
            EMBEDDING_MODEL,
        )
        embedder = _create_embedder()
        with _session() as session:
            result = pipeline.ingest_handbook(
                session=session,
                source_root=DEFAULT_ROOT,
                strategy=strategy,
                config=config,
                embedder=embedder,
            )
    except Exception as error:
        reason = "ingestion_failed"
        run_id = None
        if pipeline is not None and isinstance(error, pipeline.IngestionError):
            reason = error.reason_code
            run_id = error.run_id
        if logger is not None:
            logger.error(
                "CLI failed invocation_id={} run_id={} reason={}",
                invocation_id,
                run_id,
                reason,
            )
        suffix = f" run_id={run_id}" if isinstance(run_id, UUID) else ""
        print(f"Ingestion failed: {reason}.{suffix}", file=sys.stderr)  # noqa: T201
        return 1

    status = "skipped" if result.skipped else "completed"
    logger.info(
        "Snapshot finished invocation_id={} run_id={} snapshot_fingerprint={} "
        "status={} documents={} chunks={} cache_hits={} api_inputs={}",
        invocation_id,
        result.run_id,
        result.snapshot_fingerprint,
        status,
        result.document_count,
        result.chunk_count,
        result.reused_embeddings,
        result.generated_embeddings,
    )
    print(  # noqa: T201
        f"Ingestion {status}: run_id={result.run_id} status={status} "
        f"documents={result.document_count} chunks={result.chunk_count} "
        f"reused_embeddings={result.reused_embeddings} "
        f"generated_embeddings={result.generated_embeddings}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
