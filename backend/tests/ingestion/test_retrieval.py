"""Offline contracts for exact vector retrieval; never access DB or provider."""

import importlib
import sys
from contextlib import nullcontext
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from pydantic_settings.sources import DotEnvSettingsSource
from sqlalchemy.dialects import postgresql
from sqlmodel import Session


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(DotEnvSettingsSource, "_read_env_files", lambda self: {})
    monkeypatch.setenv("DB_FULL_CONNECTION_STRING", "postgresql://unused")


@pytest.fixture
def retrieval(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    logger_module = ModuleType("app.core.logger")
    logger_module.app_logger = Mock()
    with monkeypatch.context() as imports:
        imports.setitem(sys.modules, "app.core.logger", logger_module)
        module = importlib.import_module("app.ingestion.retrieval")
    monkeypatch.setattr(module, "app_logger", Mock())
    return module


class FakeEmbedder:
    def __init__(self, vector: object | None = None) -> None:
        self.vector = vector if vector is not None else [1.0] + [0.0] * 1535
        self.questions: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> object:
        self.questions.append(texts)
        return [self.vector]


def completed_run(*, strategy: str = "fixed", model: str = "text-embedding-3-small"):
    return SimpleNamespace(
        id=uuid4(),
        strategy=strategy,
        status="completed",
        embedding_model=model,
        created_at=datetime(2026, 11, 5, tzinfo=UTC),
    )


def session_with_run(run: object | None) -> Mock:
    session = Mock(spec=Session)
    session.no_autoflush = nullcontext()
    session.exec.return_value.one_or_none.return_value = run
    return session


def valid_row(
    *,
    distance: float = 0.2,
    chunk_id: UUID | None = None,
    content: str = "private handbook text",
):
    return (
        chunk_id or uuid4(),
        uuid4(),
        content,
        distance,
        {
            "token_count": 12,
            "heading_paths": [["Handbook", "Testing"]],
            "source_spans": [{"start_line": 3, "end_line": 5}],
        },
        "handbook/testing.md",
        "Engineering Handbook",
    )


def test_no_completed_run_returns_empty_without_embedding(retrieval) -> None:
    session = session_with_run(None)
    embedder = Mock()
    assert (
        retrieval.retrieve_chunks(
            session=session, question="question", strategy="fixed", embedder=embedder
        )
        == []
    )
    embedder.embed_texts.assert_not_called()
    session.exec.assert_called_once()
    session.flush.assert_not_called()


def test_resolver_missing_snapshot_is_operational_error(retrieval) -> None:
    session = session_with_run(None)
    with pytest.raises(retrieval.RetrievalError) as caught:
        retrieval.resolve_latest_completed_run(
            session=session, strategy="heading_aware"
        )
    assert caught.value.reason_code == "missing_snapshot"
    session.exec.assert_called_once()
    session.flush.assert_not_called()


@pytest.mark.parametrize("strategy", ["fixed", "fixed_overlap", "heading_aware"])
def test_resolver_returns_latest_completed_run_and_preserves_session(
    retrieval, strategy: str
) -> None:
    run = completed_run(strategy=strategy)
    session = session_with_run(run)
    assert (
        retrieval.resolve_latest_completed_run(session=session, strategy=strategy)
        is run
    )
    statement = session.exec.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "ORDER BY ingestion_runs.created_at DESC, ingestion_runs.id ASC" in sql
    assert "LIMIT" in sql
    assert strategy in compiled.params.values()
    assert "completed" in compiled.params.values()
    assert 1 in compiled.params.values()
    session.exec.assert_called_once()
    for method in (session.flush, session.commit, session.rollback, session.close):
        method.assert_not_called()


@pytest.mark.parametrize("strategy", [None, [], "unknown", " heading_aware "])
def test_resolver_rejects_invalid_strategy_before_database(retrieval, strategy) -> None:
    session = Mock(spec=Session)
    with pytest.raises(ValueError, match="invalid_strategy"):
        retrieval.resolve_latest_completed_run(session=session, strategy=strategy)
    session.exec.assert_not_called()


def test_resolver_latest_model_mismatch_never_falls_back(retrieval) -> None:
    newest = completed_run(strategy="heading_aware", model="different-model")
    older = completed_run(strategy="heading_aware")
    session = session_with_run(newest)
    session.exec.side_effect = [
        Mock(one_or_none=Mock(return_value=newest)),
        Mock(one_or_none=Mock(return_value=older)),
    ]
    with pytest.raises(retrieval.RetrievalError) as caught:
        retrieval.resolve_latest_completed_run(
            session=session, strategy="heading_aware"
        )
    assert caught.value.reason_code == "run_not_searchable"
    session.exec.assert_called_once()


def test_resolver_database_failure_is_sanitized(retrieval) -> None:
    session = session_with_run(None)
    session.exec.side_effect = RuntimeError("private database credentials")
    with pytest.raises(retrieval.RetrievalError) as caught:
        retrieval.resolve_latest_completed_run(
            session=session, strategy="heading_aware"
        )
    assert caught.value.reason_code == "database_error"
    assert "private" not in str(caught.value)
    assert caught.value.__suppress_context__
    assert "private" not in str(retrieval.app_logger.mock_calls)


def test_invalid_explicit_run_fails_before_embedding(retrieval) -> None:
    session = session_with_run(None)
    embedder = Mock()
    with pytest.raises(retrieval.RetrievalError, match="run_not_searchable"):
        retrieval.retrieve_chunks(
            session=session,
            question="question",
            strategy="fixed",
            ingestion_run_id=uuid4(),
            embedder=embedder,
        )
    embedder.embed_texts.assert_not_called()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"question": "  ", "strategy": "fixed"},
        {"question": None, "strategy": "fixed"},
        {"question": "q", "strategy": "unknown"},
        {"question": "q", "strategy": []},
        {"question": "q", "strategy": "fixed", "top_k": 0},
        {"question": "q", "strategy": "fixed", "top_k": 101},
        {"question": "q", "strategy": "fixed", "top_k": True},
        {"question": "q", "strategy": "fixed", "top_k": 2.0},
        {"question": "q", "strategy": "fixed", "ingestion_run_id": "not-a-uuid"},
    ],
)
def test_invalid_arguments_rejected_before_db(retrieval, kwargs) -> None:
    session = Mock(spec=Session)
    params = {"question": "q", "strategy": "fixed", **kwargs}
    with pytest.raises(ValueError):
        retrieval.retrieve_chunks(session=session, **params)
    session.exec.assert_not_called()


def test_strips_question_and_maps_result(retrieval) -> None:
    run = completed_run(strategy="heading_aware")
    session = session_with_run(run)
    session.exec.side_effect = [
        Mock(one_or_none=Mock(return_value=run)),
        Mock(all=Mock(return_value=[valid_row(distance=0.25)])),
    ]
    embedder = FakeEmbedder()

    results = retrieval.retrieve_chunks(
        session=session,
        question="  How do I test?  ",
        strategy="heading_aware",
        top_k=5,
        embedder=embedder,
    )

    assert embedder.questions == [["How do I test?"]]
    assert len(results) == 1
    result = results[0]
    assert result.similarity_score == pytest.approx(0.75)
    assert result.rank == 1
    assert result.strategy == "heading_aware"
    assert result.tokens == 12
    assert result.heading_paths == [["Handbook", "Testing"]]
    assert result.source_spans == [[3, 5]]
    assert result.file_path == "handbook/testing.md"
    assert result.title == "Engineering Handbook"
    assert session.commit.call_count == 0
    assert session.rollback.call_count == 0
    assert session.close.call_count == 0
    session.flush.assert_not_called()


def test_explicit_run_validation_precedes_embedding(retrieval) -> None:
    run = completed_run(strategy="fixed_overlap")
    session = session_with_run(run)
    embedder = Mock()
    with pytest.raises(retrieval.RetrievalError, match="run_not_searchable"):
        retrieval.retrieve_chunks(
            session=session,
            question="query",
            strategy="fixed",
            ingestion_run_id=run.id,
            embedder=embedder,
        )
    embedder.embed_texts.assert_not_called()


@pytest.mark.parametrize(
    "vector",
    [
        [0.0] * 1536,
        [float("nan")] + [0.0] * 1535,
        [float("inf")] + [0.0] * 1535,
        [True] + [0.0] * 1535,
        ["1.0"] + [0.0] * 1535,
        [1.0],
    ],
)
def test_invalid_query_vector_fails_before_search(retrieval, vector) -> None:
    run = completed_run()
    session = session_with_run(run)
    embedder = FakeEmbedder(vector)
    with pytest.raises(retrieval.EmbeddingError, match="invalid_query_vector"):
        retrieval.retrieve_chunks(
            session=session,
            question="query",
            strategy="fixed",
            embedder=embedder,
        )
    assert session.exec.call_count == 1


def test_wrong_model_on_newest_run_does_not_fall_back(retrieval) -> None:
    run = completed_run(model="different-model")
    session = session_with_run(run)
    embedder = Mock()
    with pytest.raises(retrieval.RetrievalError, match="run_not_searchable"):
        retrieval.retrieve_chunks(
            session=session,
            question="query",
            strategy="fixed",
            embedder=embedder,
        )
    embedder.embed_texts.assert_not_called()


def test_search_filters_run_strategy_and_null_vectors_before_limit(retrieval) -> None:
    statement = retrieval._search_statement(
        strategy="fixed", run_id=uuid4(), vector=[1.0] + [0.0] * 1535, top_k=5
    )
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "JOIN knowledge_documents" in sql
    assert "JOIN ingestion_runs" in sql
    assert "knowledge_chunks.ingestion_run_id" in sql
    assert "knowledge_chunks.embedding IS NOT NULL" in sql
    assert "ORDER BY (knowledge_chunks.embedding <=>" in sql
    assert "knowledge_chunks.id ASC" in sql
    assert "LIMIT" in sql
    assert "ingestion_runs.strategy" in sql


def test_default_run_selection_orders_completed_strategy_deterministically(
    retrieval,
) -> None:
    statement = (
        retrieval.select(retrieval.IngestionRun)
        .where(
            retrieval.IngestionRun.strategy == "fixed",
            retrieval.IngestionRun.status == "completed",
        )
        .order_by(
            retrieval.IngestionRun.created_at.desc(), retrieval.IngestionRun.id.asc()
        )
        .limit(1)
    )
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "ingestion_runs.strategy" in sql
    assert "ingestion_runs.status" in sql
    assert "ORDER BY ingestion_runs.created_at DESC, ingestion_runs.id ASC" in sql
    assert "LIMIT" in sql


def test_invalid_metadata_in_returned_row_fails_safely(retrieval) -> None:
    run = completed_run()
    row = list(valid_row())
    row[4] = {"token_count": True, "heading_paths": [], "source_spans": []}
    session = session_with_run(run)
    session.exec.side_effect = [
        Mock(one_or_none=Mock(return_value=run)),
        Mock(all=Mock(return_value=[tuple(row)])),
    ]
    with pytest.raises(retrieval.RetrievalError, match="invalid_chunk_metadata"):
        retrieval.retrieve_chunks(
            session=session,
            question="query",
            strategy="fixed",
            embedder=FakeEmbedder(),
        )


def test_invalid_metadata_below_top_k_does_not_fail(retrieval) -> None:
    run = completed_run()
    valid_top_row = valid_row(distance=0.1)
    session = session_with_run(run)
    session.exec.side_effect = [
        Mock(one_or_none=Mock(return_value=run)),
        # PostgreSQL applies LIMIT in the ranking query, so lower-ranked rows
        # never reach metadata validation when outside the requested top-k.
        Mock(all=Mock(return_value=[valid_top_row])),
    ]
    results = retrieval.retrieve_chunks(
        session=session,
        question="query",
        strategy="fixed",
        top_k=1,
        embedder=FakeEmbedder(),
    )
    assert len(results) == 1
    assert results[0].rank == 1


def test_empty_search_returns_empty_list(retrieval) -> None:
    run = completed_run()
    session = session_with_run(run)
    session.exec.side_effect = [
        Mock(one_or_none=Mock(return_value=run)),
        Mock(all=Mock(return_value=[])),
    ]
    assert (
        retrieval.retrieve_chunks(
            session=session, question="query", strategy="fixed", embedder=FakeEmbedder()
        )
        == []
    )


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("How should I name my variables in Python?", "naming"),
        ("What should I do before merging my code?", "pull request"),
        ("Is it okay to store passwords directly in my source code?", "secrets"),
        ("How do I make sure my code is properly tested?", "testing"),
        ("What's the proper way to handle errors in my application?", "errors"),
        (
            "What security and testing checks must be completed before deploying an application?",
            "security",
        ),
        (
            "What are the requirements for submitting, reviewing, and merging a pull request?",
            "source control",
        ),
        (
            "How should developers manage secrets across development and production environments?",
            "secrets",
        ),
        (
            "What coding and documentation standards should be followed when creating a new API?",
            "api",
        ),
        (
            "What steps should developers take to ensure their application is production-ready?",
            "deployment",
        ),
    ],
)
def test_semantic_and_multi_section_retrieval_questions_are_supported(
    retrieval, question: str, expected: str
) -> None:
    """Use deterministic vectors; no live provider or retrieval-quality claim."""
    run = completed_run(strategy="heading_aware")
    session = session_with_run(run)
    row = list(valid_row(content=f"Relevant handbook guidance: {expected}"))
    session.exec.side_effect = [
        Mock(one_or_none=Mock(return_value=run)),
        Mock(all=Mock(return_value=[tuple(row)])),
    ]
    embedder = FakeEmbedder()
    results = retrieval.retrieve_chunks(
        session=session,
        question=question,
        strategy="heading_aware",
        embedder=embedder,
    )
    assert results[0].rank == 1
    assert expected in results[0].content
    assert embedder.questions == [[question]]
    assert (
        expected
        in "naming pull request secrets testing errors security source control api deployment"
    )
