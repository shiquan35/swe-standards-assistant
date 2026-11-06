"""Search completed handbook snapshots and print ranked source excerpts."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlmodel import Session

    from app.ingestion.retrieval import RetrievalResult


def _get_retrieval():
    # Keep --help and argument validation independent of DB/env configuration.
    from app.ingestion import retrieval

    return retrieval


@contextmanager
def _session() -> Generator[Session]:
    from sqlmodel import Session

    from app.core.db import engine

    with Session(engine) as session:
        yield session


def _format_results(
    query: str, strategy: str, top_k: int, results: Sequence[RetrievalResult]
) -> str:
    sections = [f"Query: {query}\nStrategy: {strategy}\nTop-K: {top_k}"]
    for result in results:
        headings = "; ".join(" > ".join(path) for path in result.heading_paths if path)
        lines = ", ".join(f"{start}-{end}" for start, end in result.source_spans)
        sections.append(
            f"Rank: {result.rank}\n"
            f"Similarity: {result.similarity_score:.4f}\n"
            f"Document: {result.title}\n"
            f"Heading: {headings or '(none)'}\n"
            f"Source: {result.file_path}\n"
            f"Lines: {lines or '(none)'}\n"
            f"Content:\n{result.content}"
        )
    if not results:
        sections.append("No matching chunks found.")
    return "\n\n".join(sections)


def main(argv: Sequence[str] | None = None) -> int:
    """Return 0 for a successful search, 1 for runtime failure, 2 for bad args."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Question to search for.")
    parser.add_argument(
        "--strategy", required=True, choices=("fixed", "fixed_overlap", "heading_aware")
    )
    parser.add_argument("--top-k", type=int, default=5, help="Result limit (1-100).")
    args = parser.parse_args(argv)
    query = args.query.strip()
    if not query:
        parser.error("query must not be empty")
    if not 1 <= args.top_k <= 100:
        parser.error("top-k must be between 1 and 100")

    retrieval = None
    try:
        retrieval = _get_retrieval()
        with _session() as session:
            results = retrieval.retrieve_chunks(
                session=session,
                question=query,
                strategy=args.strategy,
                top_k=args.top_k,
            )
        output = _format_results(query, args.strategy, args.top_k, results)
    except Exception as error:
        # Never echo provider/database exceptions, which may contain secrets.
        reason = "search_failed"
        if retrieval is not None and isinstance(
            error, (retrieval.RetrievalError, retrieval.EmbeddingError)
        ):
            if error.reason_code in {
                "database_error",
                "run_not_searchable",
                "invalid_chunk_metadata",
                "invalid_query_vector",
                "missing_api_key",
                "configuration_failed",
                "embedding_failed",
                "input_token_limit",
                "invalid_unicode",
            }:
                reason = error.reason_code
        print(f"Search failed: {reason}.", file=sys.stderr)  # noqa: T201
        return 1

    print(output)  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
