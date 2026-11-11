"""Answer one handbook question with cited claims; use --json for scripts."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING

from app.rag.errors import RagError

if TYPE_CHECKING:
    from sqlmodel import Session

    from app.rag.models import RagResponse


def _write_error(reason: str, message: str, *, json_mode: bool) -> None:
    output = (
        json.dumps({"error": {"reason_code": reason, "message": message}})
        if json_mode
        else f"Handbook answer failed: {reason}. {message}"
    )
    print(output, file=sys.stderr)  # noqa: T201


class _Parser(argparse.ArgumentParser):
    """Never echo rejected arguments, which can contain questions or secrets."""

    def __init__(self, *, json_mode: bool) -> None:
        super().__init__(description=__doc__, allow_abbrev=False)
        self.json_mode = json_mode

    def error(self, _message: str) -> None:
        _write_error(
            "invalid_arguments",
            "Provide one positional question and optional --json.",
            json_mode=self.json_mode,
        )
        raise SystemExit(2)


def _get_service():
    # Importing this module loads settings; defer until arguments are valid.
    from app.rag import service

    return service


@contextmanager
def _session() -> Generator[Session]:
    from sqlmodel import Session

    from app.core.db import engine

    with Session(engine) as session:
        yield session


def _format_response(response: RagResponse) -> str:
    """Compose claims; stable source numbers follow application citation order."""
    numbers = {
        citation.chunk_id: index
        for index, citation in enumerate(response.citations, start=1)
    }
    sections = [f"Status: {response.status}"]
    if response.claims:
        sections.append(
            "\n".join(
                f"{claim.text} "
                + " ".join(f"[{numbers[source]}]" for source in claim.citation_ids)
                for claim in response.claims
            )
        )
    if response.reason is not None:
        sections.append(f"Reason: {response.reason}")
    if response.unanswered_parts:
        sections.append(
            "Unanswered parts:\n"
            + "\n".join(f"- {part}" for part in response.unanswered_parts)
        )
    if response.clarifying_question is not None:
        sections.append(f"Clarifying question: {response.clarifying_question}")
    if response.citations:
        sources = []
        for citation in response.citations:
            headings = "; ".join(
                " > ".join(path) for path in citation.heading_paths if path
            )
            spans = ", ".join(f"{start}-{end}" for start, end in citation.source_spans)
            sources.append(
                f"[{numbers[citation.chunk_id]}] Title: {citation.title or '(none)'}\n"
                f"Path: {citation.file_path or '(none)'}\n"
                f"Headings: {headings or '(none)'}\n"
                f"Lines: {spans or '(none)'}"
            )
        sections.append("Sources:\n" + "\n\n".join(sources))
    sections.append(f"Ingestion run: {response.ingestion_run_id}")
    return "\n\n".join(sections)


def main(argv: Sequence[str] | None = None) -> int:
    """Return 0 for content outcomes, 1 for runtime errors, 2 for invalid args.

    Application logs are suppressed for this CLI invocation so stderr remains
    one safe, mode-matched error rather than mixed JSON and diagnostic output.
    Direct service callers retain the service's operational metadata logs.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    json_mode = "--json" in arguments
    parser = _Parser(json_mode=json_mode)
    parser.add_argument("question", help="One handbook question.")
    parser.add_argument(
        "--json", action="store_true", help="Emit the typed JSON response."
    )
    try:
        args = parser.parse_args(arguments)
    except SystemExit as error:
        return int(error.code or 0)
    question = args.question.strip()
    if not question:
        error = RagError("invalid_question")
        _write_error(error.reason_code, str(error), json_mode=args.json)
        return 2

    # Neither settings nor DB nor provider modules are imported before parsing.
    from loguru import logger

    logger.disable("app")
    try:
        service = _get_service()
        with _session() as session:
            response = service.answer_question(session=session, question=question)
        output = response.model_dump_json() if args.json else _format_response(response)
    except Exception as error:
        safe = RagError(
            error.reason_code if isinstance(error, RagError) else "rag_failed"
        )
        _write_error(safe.reason_code, str(safe), json_mode=args.json)
        return 1
    finally:
        logger.enable("app")

    print(output)  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
