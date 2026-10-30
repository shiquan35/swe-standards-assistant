"""Inspect transient handbook chunks without persistence or embedding services."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from app.ingestion import (
    ChunkingConfig,
    ChunkingError,
    ChunkStrategy,
    chunk_document,
    parse_markdown_file,
)

DEFAULT_PATH = (
    Path(__file__).resolve().parents[2]
    / "knowledge_base"
    / "engineering-handbook"
    / "api-standards.md"
)


def main(argv: Sequence[str] | None = None) -> int:
    """Print every candidate verbatim; failures disclose no document content."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH)
    parser.add_argument(
        "--strategy",
        choices=("fixed", "fixed_overlap", "heading_aware"),
        default="heading_aware",
    )
    parser.add_argument("--max-tokens", type=int, default=500)
    parser.add_argument(
        "--overlap-tokens",
        type=int,
        default=None,
        help="Overlap target (default: 0 for fixed, 100 otherwise).",
    )
    args = parser.parse_args(argv)
    strategy: ChunkStrategy = args.strategy
    overlap = args.overlap_tokens
    if overlap is None:
        overlap = 0 if strategy == "fixed" else 100
    try:
        config = ChunkingConfig(args.max_tokens, overlap)
        if strategy == "fixed" and overlap != 0:
            parser.error("fixed strategy requires zero overlap")
    except ValueError:
        parser.error("invalid token budget configuration")

    try:
        document = parse_markdown_file(args.path)
        candidates = chunk_document(document, strategy, config)
    except Exception as error:
        # Never echo exception messages: filesystem/parser errors may contain
        # the supplied path, title, source text, or other sensitive material.
        reason = "processing_failed"
        if isinstance(error, ChunkingError) and error.reason_code in {
            "invalid_unicode",
            "token_budget_unrepresentable",
        }:
            reason = error.reason_code
        print(f"Chunking failed: {reason}.", file=sys.stderr)  # noqa: T201
        return 1

    if not candidates:
        print("No chunk candidates produced.")  # noqa: T201
        return 0
    for candidate in candidates:
        print(f"Ordinal: {candidate.ordinal}")  # noqa: T201
        print(f"Strategy: {candidate.strategy}")  # noqa: T201
        print(f"Tokens: {candidate.token_count}")  # noqa: T201
        print(f"Actual overlap tokens: {candidate.actual_overlap_tokens}")  # noqa: T201
        print(f"Source: {candidate.source_path}")  # noqa: T201
        print(  # noqa: T201
            "Heading paths: " + json.dumps(candidate.heading_paths, ensure_ascii=False)
        )
        print(  # noqa: T201
            "Source spans: "
            + json.dumps(
                [[span.start_line, span.end_line] for span in candidate.source_spans]
            )
        )
        print(
            f"Heading prefix omitted: {candidate.heading_prefix_omitted}"
        )  # noqa: T201
        print("Content:")  # noqa: T201
        print(candidate.content)  # noqa: T201
        print()  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
