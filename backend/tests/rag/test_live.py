"""Paid, non-destructive smoke test; never enabled by normal offline discovery."""

import os

import pytest


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_RAG_TEST") != "1",
    reason="Paid real OpenAI/app DB smoke test requires RUN_LIVE_RAG_TEST=1",
)
def test_live_handbook_answer() -> None:
    # Imports (including settings/DB) happen only after the explicit live opt-in.
    from openai import OpenAI
    from sqlmodel import Session

    from app.core.db import engine
    from app.core.env import env
    from app.rag.models import RagResponse
    from app.rag.service import answer_question

    if env.OPENAI_API_KEY is None or not env.OPENAI_API_KEY.get_secret_value().strip():
        pytest.fail("Live RAG smoke test requires configured OpenAI credentials")
    with (
        OpenAI(api_key=env.OPENAI_API_KEY.get_secret_value(), max_retries=0) as client,
        Session(engine) as session,
    ):
        response = answer_question(
            session=session,
            question="What are the requirements for approving a pull request?",
            openai_client=client,
        )
    validated = RagResponse.model_validate_json(response.model_dump_json())
    assert validated.ingestion_run_id is not None
    # This known handbook question must exercise generation, not empty retrieval.
    assert validated.status in {"answered", "partial", "clarification_needed"}
    assert validated.claims
    assert validated.citations
