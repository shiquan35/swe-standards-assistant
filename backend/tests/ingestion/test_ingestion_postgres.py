"""Destructive, operator-migrated PostgreSQL contracts; never use the app engine.

Run this file with --confcutdir=tests/ingestion (see backend/README.md).
Both TEST_DATABASE_URL and TEST_DATABASE_ALLOW_DESTRUCTIVE=1 are mandatory.
Only the four public ingestion tables are truncated, without CASCADE. Pipeline
helpers commit, so an outer rollback or a private schema cannot isolate them.
"""

import hashlib
import importlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Event, current_thread
from types import ModuleType
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool
from sqlmodel import Session, select

OPTED_IN = bool(os.environ.get("TEST_DATABASE_URL")) and (
    os.environ.get("TEST_DATABASE_ALLOW_DESTRUCTIVE") == "1"
)
pytestmark = pytest.mark.skipif(
    not OPTED_IN,
    reason="Requires explicit TEST_DATABASE_URL and TEST_DATABASE_ALLOW_DESTRUCTIVE=1",
)
BACKEND = Path(__file__).resolve().parents[2]
TABLES = (
    "knowledge_chunks",
    "ingestion_run_documents",
    "knowledge_documents",
    "ingestion_runs",
)
TRUNCATE = text("TRUNCATE TABLE " + ", ".join(f"public.{name}" for name in TABLES))


def _assert_migrated_schema(connection):
    """Read scripts/catalog only: never load env.py or execute migrations."""
    from app.models.knowledge import (
        IngestionRun,
        IngestionRunDocument,
        KnowledgeChunk,
        KnowledgeDocument,
    )

    heads = ScriptDirectory(str(BACKEND / "alembic")).get_heads()
    assert len(heads) == 1, "Operator must resolve local Alembic heads first"
    catalog = inspect(connection)
    assert catalog.has_table(
        "alembic_version", schema="public"
    ), "Operator must migrate the disposable database first"
    versions = (
        connection.execute(text("SELECT version_num FROM public.alembic_version"))
        .scalars()
        .all()
    )
    assert versions == heads, "Disposable database must match the single local head"
    for model in (
        KnowledgeDocument,
        IngestionRun,
        IngestionRunDocument,
        KnowledgeChunk,
    ):
        table = model.__table__
        assert catalog.has_table(table.name, schema="public")
        columns = {
            col["name"]: col for col in catalog.get_columns(table.name, schema="public")
        }
        assert set(columns) == set(table.columns.keys())
        for column in table.columns:
            actual = columns[column.name]
            assert actual["nullable"] == column.nullable
            assert (
                str(actual["type"]).upper()
                == str(column.type.compile(dialect=connection.dialect)).upper()
            )
            if column.server_default is not None:
                assert actual["default"] is not None
        primary_key = catalog.get_pk_constraint(table.name, schema="public")
        assert primary_key["constrained_columns"] == [
            col.name for col in table.primary_key.columns
        ]
        checks = {
            check["name"]: check["sqltext"]
            for check in catalog.get_check_constraints(table.name, schema="public")
        }
        for constraint in table.constraints:
            if constraint.__class__.__name__ == "CheckConstraint":
                assert (
                    constraint.name in checks
                ), f"Missing migrated check: {constraint.name}; operator migration required"
                assert checks[constraint.name]
            elif constraint.__class__.__name__ == "UniqueConstraint":
                expected = [column.name for column in constraint.columns]
                assert any(
                    unique["column_names"] == expected
                    for unique in catalog.get_unique_constraints(
                        table.name, schema="public"
                    )
                ), f"Missing unique constraint on {table.name}"
        foreign_keys = catalog.get_foreign_keys(table.name, schema="public")
        assert len(foreign_keys) == len(table.foreign_key_constraints)
        for constraint in table.foreign_key_constraints:
            expected = [column.name for column in constraint.columns]
            actual = next(
                fk for fk in foreign_keys if fk["constrained_columns"] == expected
            )
            assert actual["referred_table"] == constraint.referred_table.name
            assert actual["referred_schema"] in {None, "public"}
            assert actual["referred_columns"] == [
                element.column.name for element in constraint.elements
            ]
            assert actual["options"]["ondelete"].upper() == "CASCADE"
    types = dict(
        connection.execute(
            text(
                "SELECT a.attname, format_type(a.atttypid, a.atttypmod) "
                "FROM pg_attribute a WHERE a.attrelid = 'public.knowledge_chunks'::regclass "
                "AND a.attname IN ('metadata', 'embedding')"
            )
        ).all()
    )
    assert types == {"metadata": "jsonb", "embedding": "vector(1536)"}
    assert connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
    ).scalar_one()


@pytest.fixture(scope="module")
def postgres_engine():
    # Repeat the gate here: direct fixture use must also fail closed.
    if not OPTED_IN:
        pytest.skip("Disposable PostgreSQL destructive opt-ins are absent")
    try:
        url = make_url(os.environ["TEST_DATABASE_URL"])
    except Exception:
        pytest.fail("Invalid TEST_DATABASE_URL (value withheld)", pytrace=False)
    if url.drivername not in {"postgresql", "postgresql+psycopg2"}:
        pytest.skip("TEST_DATABASE_URL must select synchronous PostgreSQL/psycopg2")
    if not url.database or url.database.lower() in {
        "postgres",
        "template0",
        "template1",
    }:
        pytest.skip(
            "A dedicated disposable database, not a maintenance DB, is required"
        )
    engine = create_engine(
        url.set(drivername="postgresql+psycopg2"),
        poolclass=NullPool,
        echo=False,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 5,
            "options": "-c search_path=public -c lock_timeout=1500 -c statement_timeout=5000",
        },
    )
    # A session-level advisory lock protects against another copy of this suite.
    # No CASCADE: unrelated tables with incoming FKs cause cleanup to fail safely.
    try:
        try:
            guard = engine.connect()
        except Exception:
            pytest.fail(
                "Cannot connect to disposable PostgreSQL (details withheld)",
                pytrace=False,
            )
        with guard:
            locked = guard.execute(
                text("SELECT pg_try_advisory_lock(1937006963, 1768843049)")
            ).scalar_one()
            guard.commit()
            if not locked:
                pytest.fail(
                    "Another ingestion PostgreSQL suite owns this database",
                    pytrace=False,
                )
            try:
                _assert_migrated_schema(guard)
                guard.commit()
                yield engine
            finally:
                guard.rollback()
                guard.execute(text("SELECT pg_advisory_unlock(1937006963, 1768843049)"))
                guard.commit()
    finally:
        engine.dispose()


@pytest.fixture
def db(postgres_engine):
    with postgres_engine.begin() as connection:
        connection.execute(TRUNCATE)
    try:
        yield postgres_engine
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(TRUNCATE)


@pytest.fixture
def pipeline(db, monkeypatch):
    # Never initialize application settings, dotenv, the development engine, or
    # real logger sinks. Every DB session below uses only the gated test engine.
    import httpx
    import openai
    from pydantic_settings.sources import DotEnvSettingsSource

    def forbidden(*_args, **_kwargs):
        pytest.fail("Integration tests must not load dotenv or call an HTTP API")

    monkeypatch.setattr(DotEnvSettingsSource, "_read_env_files", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(openai, "OpenAI", forbidden)
    logger_module = ModuleType("app.core.logger")
    logger_module.app_logger = Mock()
    with monkeypatch.context() as imports:
        imports.setitem(sys.modules, "app.core.logger", logger_module)
        module = importlib.import_module("app.ingestion.pipeline")
    monkeypatch.setattr(module, "app_logger", Mock())
    monkeypatch.setattr(module, "EmbeddingService", forbidden)
    assert db.dialect.name == "postgresql"
    return module


def _documents(pipeline):
    from app.ingestion.chunk_models import ChunkCandidate, ChunkPart
    from app.ingestion.markdown_models import SourceRange

    path = "handbook/guide.md"
    content = "Café rules for teams."
    candidate = ChunkCandidate(
        ordinal=0,
        strategy="fixed",
        content=content,
        token_count=6,
        source_path=path,
        heading_paths=[["Guide", "Règles"]],
        source_spans=[SourceRange(3, 5)],
        parts=[ChunkPart(0, len(content), "source", 10, 10 + len(content))],
        actual_overlap_tokens=0,
        heading_prefix_omitted=True,
    )
    return [
        pipeline.PreparedDocument(
            path,
            hashlib.sha256(b"captured guide bytes").hexdigest(),
            "Guide",
            [candidate],
        ),
        pipeline.PreparedDocument(
            "handbook/empty.md", hashlib.sha256(b"# Empty\n").hexdigest(), "Empty", []
        ),
    ]


def _embedder():
    embedder = Mock()
    embedder.embed_texts.side_effect = lambda texts: [[0.25] * 1536 for _ in texts]
    return embedder


def _ingest(pipeline, db, monkeypatch, documents, embedder=None):
    monkeypatch.setattr(pipeline, "prepare_documents", Mock(return_value=documents))
    with Session(db) as session:
        return pipeline.ingest_handbook(
            session=session,
            source_root=Path("unused-prepared-source"),
            strategy="fixed",
            config=pipeline.ChunkingConfig(500, 0),
            embedder=embedder if embedder is not None else _embedder(),
        )


def _claim(pipeline, db, fingerprint=None):
    with Session(db) as session:
        return pipeline._claim_run(
            session,
            fingerprint or uuid4().hex * 2,
            "fixed",
            pipeline.ChunkingConfig(500, 0),
        )


def _counts(db):
    with db.connect() as connection:
        return {
            name: connection.execute(
                text(f"SELECT count(*) FROM public.{name}")
            ).scalar_one()
            for name in TABLES
        }


def test_operator_migrations_match_catalog(db):
    with db.connect() as connection:
        _assert_migrated_schema(connection)


def test_claim_conflict_running_failed_retry_and_completed(db, pipeline):
    fingerprint = uuid4().hex * 2
    run_id, token = _claim(pipeline, db, fingerprint)
    assert token is not None
    with pytest.raises(pipeline.IngestionError, match="^run_already_running$"):
        _claim(pipeline, db, fingerprint)
    with Session(db) as session:
        pipeline._mark_failed(session, run_id, token)
    retry_id, retry_token = _claim(pipeline, db, fingerprint)
    assert retry_id == run_id
    assert retry_token is not None and retry_token != token
    with Session(db) as session:
        pipeline._publish_snapshot(session, retry_id, retry_token, [], {})
    assert _claim(pipeline, db, fingerprint) == (run_id, None)
    assert _counts(db)["ingestion_runs"] == 1


def test_ingest_atomic_visibility_jsonb_vector_noop_and_historical_hashes(
    db, pipeline, monkeypatch
):
    documents = _documents(pipeline)
    embedder = _embedder()
    observed = []

    def observe_uncommitted(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO knowledge_documents") and not observed:
            # A different connection sees the claim, not any partial publication.
            counts = _counts(db)
            assert counts == dict.fromkeys(TABLES, 0) | {"ingestion_runs": 1}
            with Session(db) as reader:
                assert (
                    reader.exec(select(pipeline.IngestionRun.status)).one() == "running"
                )
            observed.append(True)

    event.listen(db, "after_cursor_execute", observe_uncommitted)
    try:
        first = _ingest(pipeline, db, monkeypatch, documents, embedder)
    finally:
        event.remove(db, "after_cursor_execute", observe_uncommitted)
    assert observed == [True]
    assert (first.document_count, first.chunk_count, first.generated_embeddings) == (
        2,
        1,
        1,
    )
    before = _counts(db)
    repeated = _ingest(pipeline, db, monkeypatch, documents, embedder)
    assert repeated.skipped and repeated.run_id == first.run_id
    assert _counts(db) == before
    embedder.embed_texts.assert_called_once_with([documents[0].candidates[0].content])
    with Session(db) as session:
        chunk = session.exec(select(pipeline.KnowledgeChunk)).one()
        original_chunk_id = chunk.id
        assert chunk.content == documents[0].candidates[0].content
        assert chunk.metadata_ == pipeline.candidate_metadata(
            documents[0].candidates[0]
        )
        assert chunk.heading == "Règles"
        assert list(chunk.embedding) == pytest.approx([0.25] * 1536)
        mappings = session.exec(select(pipeline.IngestionRunDocument)).all()
        assert len(mappings) == 2  # Includes the zero-candidate document.
        run = session.get(pipeline.IngestionRun, first.run_id)
        assert run.status == "completed" and run.execution_token is None
    changed = [
        replace(documents[0], source_hash="b" * 64, title="Updated"),
        documents[1],
    ]
    second = _ingest(pipeline, db, monkeypatch, changed, embedder)
    assert second.run_id != first.run_id and not second.skipped
    assert (second.reused_embeddings, second.generated_embeddings) == (1, 0)
    assert embedder.embed_texts.call_count == 1
    with Session(db) as session:
        doc = session.exec(
            select(pipeline.KnowledgeDocument).where(
                pipeline.KnowledgeDocument.file_path == documents[0].relative_path
            )
        ).one()
        assert (doc.title, doc.content_hash) == ("Updated", "b" * 64)
        old = session.get(pipeline.IngestionRunDocument, (first.run_id, doc.id))
        new = session.get(pipeline.IngestionRunDocument, (second.run_id, doc.id))
        assert old.source_hash == documents[0].source_hash
        assert new.source_hash == "b" * 64
        chunks = session.exec(select(pipeline.KnowledgeChunk)).all()
        assert len(chunks) == 2 and len({chunk.id for chunk in chunks}) == 2
        assert original_chunk_id in {chunk.id for chunk in chunks}
        assert {chunk.ingestion_run_id for chunk in chunks} == {
            first.run_id,
            second.run_id,
        }


def test_all_zero_candidates_publish_source_hash_without_embeddings(
    db, pipeline, monkeypatch
):
    empty = _documents(pipeline)[1]
    embedder = _embedder()
    result = _ingest(pipeline, db, monkeypatch, [empty], embedder)
    assert (result.document_count, result.chunk_count, result.generated_embeddings) == (
        1,
        0,
        0,
    )
    embedder.embed_texts.assert_not_called()
    with Session(db) as session:
        mapping = session.exec(select(pipeline.IngestionRunDocument)).one()
        assert mapping.source_hash == empty.source_hash
        assert session.exec(select(pipeline.KnowledgeChunk)).all() == []


def test_publish_failure_rolls_back_document_values_and_every_snapshot_row(
    db, pipeline, monkeypatch
):
    documents = _documents(pipeline)
    first = _ingest(pipeline, db, monkeypatch, documents)
    with db.connect() as connection:
        before = connection.execute(
            text("SELECT * FROM public.knowledge_documents ORDER BY file_path")
        ).all()
    counts = _counts(db)
    changed = [
        replace(documents[0], source_hash="c" * 64, title="Must roll back"),
        replace(documents[1], relative_path="handbook/new.md"),
    ]
    attempted = []

    def force_failure(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO knowledge_chunks"):
            attempted.append(True)
            raise RuntimeError("forced_publication_failure")

    event.listen(db, "before_cursor_execute", force_failure)
    try:
        with pytest.raises(pipeline.IngestionError, match="^ingestion_failed$"):
            _ingest(pipeline, db, monkeypatch, changed)
    finally:
        event.remove(db, "before_cursor_execute", force_failure)
    assert attempted
    with db.connect() as connection:
        assert (
            connection.execute(
                text("SELECT * FROM public.knowledge_documents ORDER BY file_path")
            ).all()
            == before
        )  # Includes title, hash, and updated_at.
    assert _counts(db) == counts | {"ingestion_runs": 2}
    with Session(db) as session:
        failed = session.exec(
            select(pipeline.IngestionRun).where(
                pipeline.IngestionRun.id != first.run_id
            )
        ).one()
        assert failed.status == "failed" and failed.execution_token is None
        assert (
            session.exec(
                select(pipeline.KnowledgeChunk).where(
                    pipeline.KnowledgeChunk.ingestion_run_id == failed.id
                )
            ).all()
            == []
        )
        assert (
            session.exec(
                select(pipeline.IngestionRunDocument).where(
                    pipeline.IngestionRunDocument.ingestion_run_id == failed.id
                )
            ).all()
            == []
        )


def test_separate_sessions_recovery_fences_stale_publish_and_failure(db, pipeline):
    fingerprint = uuid4().hex * 2
    run_id, stale_token = _claim(pipeline, db, fingerprint)
    # Preload an identity map too: locked reads must refresh stale ORM state.
    with Session(db, expire_on_commit=False) as stale:
        stale_run = stale.get(pipeline.IngestionRun, run_id)
        stale.commit()
        with Session(db) as recovery:
            pipeline.recover_ingestion_run(recovery, run_id)
        with Session(db) as reader:
            recovered = reader.get(pipeline.IngestionRun, run_id)
            assert recovered.status == "failed" and recovered.execution_token is None
        with Session(db) as recovery:
            with pytest.raises(pipeline.IngestionError, match="^run_not_running$"):
                pipeline.recover_ingestion_run(recovery, run_id)
        _, owner = _claim(pipeline, db, fingerprint)
        assert owner is not None and owner != stale_token
        assert stale_run.execution_token == stale_token
        with pytest.raises(pipeline.IngestionError, match="^execution_ownership_lost$"):
            pipeline._publish_snapshot(
                stale, run_id, stale_token, _documents(pipeline), {}
            )
        pipeline._mark_failed(stale, run_id, stale_token)
    assert _counts(db) == dict.fromkeys(TABLES, 0) | {"ingestion_runs": 1}
    with Session(db) as reader:
        current = reader.get(pipeline.IngestionRun, run_id)
        assert (current.status, current.execution_token) == ("running", owner)
    with Session(db) as publisher:
        pipeline._publish_snapshot(publisher, run_id, owner, [], {})
    with Session(db) as stale:
        pipeline._mark_failed(stale, run_id, owner)
    with Session(db) as reader:
        assert reader.get(pipeline.IngestionRun, run_id).status == "completed"
    with Session(db) as recovery:
        with pytest.raises(pipeline.IngestionError, match="^run_not_found$"):
            pipeline.recover_ingestion_run(recovery, uuid4())


def test_concurrent_same_fingerprint_has_one_owner(db, pipeline):
    barrier = Barrier(2, timeout=5)
    fingerprint = uuid4().hex * 2

    def claim():
        barrier.wait()
        try:
            run_id, token = _claim(pipeline, db, fingerprint)
            return run_id, token, None
        except pipeline.IngestionError as error:
            return error.run_id, None, error.reason_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(claim) for _ in range(2)]
        results = [future.result(timeout=12) for future in futures]
    assert len({result[0] for result in results}) == 1
    assert sum(result[1] is not None for result in results) == 1
    assert sorted(result[2] or "claimed" for result in results) == [
        "claimed",
        "run_already_running",
    ]
    assert _counts(db)["ingestion_runs"] == 1


@pytest.mark.parametrize("holder", ["publish", "recover"])
def test_row_lock_serializes_recovery_and_publication(db, pipeline, holder):
    run_id, token = _claim(pipeline, db)
    documents = _documents(pipeline)
    vectors = {documents[0].candidates[0].content: [0.25] * 1536}
    acquired, release = Event(), Event()
    errors = []

    def pause_locked_owner(_conn, _cursor, statement, _parameters, _context, _many):
        if (
            current_thread().name.startswith("row-lock-owner")
            and "FOR UPDATE" in statement.upper()
            and not acquired.is_set()
        ):
            acquired.set()  # The real PostgreSQL row lock is already held.
            assert release.wait(timeout=8), "Timed out releasing row-lock owner"

    def record_lock_timeout(context):
        errors.append(getattr(context.original_exception, "pgcode", None))

    def operate(operation):
        with Session(db) as session:
            if operation == "publish":
                pipeline._publish_snapshot(session, run_id, token, documents, vectors)
            else:
                pipeline.recover_ingestion_run(session, run_id)

    competitor = "recover" if holder == "publish" else "publish"
    event.listen(db, "after_cursor_execute", pause_locked_owner)
    event.listen(db, "handle_error", record_lock_timeout)
    try:
        with ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="row-lock-owner"
        ) as executor:
            future = executor.submit(operate, holder)
            try:
                assert acquired.wait(timeout=5), "Owner never acquired the row lock"
                if competitor == "recover":
                    with pytest.raises(
                        pipeline.IngestionError, match="^recovery_failed$"
                    ):
                        operate(competitor)
                else:
                    with pytest.raises(DBAPIError) as error:
                        operate(competitor)
                    assert error.value.orig.pgcode == "55P03"
                assert errors == ["55P03"]  # lock_timeout, not a timing/sleep guess.
            finally:
                release.set()
            future.result(timeout=12)
    finally:
        release.set()
        event.remove(db, "after_cursor_execute", pause_locked_owner)
        event.remove(db, "handle_error", record_lock_timeout)
    reason = (
        "run_not_running" if competitor == "recover" else "execution_ownership_lost"
    )
    with pytest.raises(pipeline.IngestionError, match=f"^{reason}$"):
        operate(competitor)
    counts = _counts(db)
    assert counts["knowledge_chunks"] == (1 if holder == "publish" else 0)
    assert counts["ingestion_run_documents"] == (2 if holder == "publish" else 0)


@pytest.mark.parametrize("parent", ["ingestion_runs", "knowledge_documents"])
def test_database_delete_cascades_without_orm_help(db, pipeline, monkeypatch, parent):
    result = _ingest(pipeline, db, monkeypatch, _documents(pipeline))
    with db.begin() as connection:
        if parent == "ingestion_runs":
            connection.execute(
                text("DELETE FROM public.ingestion_runs WHERE id = :id"),
                {"id": result.run_id},
            )
        else:
            connection.execute(text("DELETE FROM public.knowledge_documents"))
    counts = _counts(db)
    assert counts["knowledge_chunks"] == counts["ingestion_run_documents"] == 0
    assert counts["knowledge_documents"] == (2 if parent == "ingestion_runs" else 0)
    assert counts["ingestion_runs"] == (0 if parent == "ingestion_runs" else 1)


@pytest.mark.parametrize(
    ("case", "sqlstate"),
    [
        ("fingerprint_unique", "23505"),
        ("path_unique", "23505"),
        ("chunk_unique", "23505"),
        ("mapping_unique", "23505"),
        ("fingerprint_length", "23514"),
        ("running_token", "23514"),
        ("status", "23514"),
        ("strategy", "23514"),
        ("max_tokens", "23514"),
        ("negative_overlap", "23514"),
        ("excess_overlap", "23514"),
        ("document_hash", "23514"),
        ("source_hash", "23514"),
        ("chunk_index", "23514"),
        ("chunk_run_fk", "23503"),
        ("chunk_document_fk", "23503"),
        ("mapping_run_fk", "23503"),
        ("mapping_document_fk", "23503"),
        ("chunk_run_nonnull", "23502"),
        ("vector_dimensions", "22000"),
    ],
)
def test_database_enforces_constraints(db, pipeline, monkeypatch, case, sqlstate):
    result = _ingest(pipeline, db, monkeypatch, _documents(pipeline))
    run = pipeline.IngestionRun.__table__
    doc = pipeline.KnowledgeDocument.__table__
    chunk = pipeline.KnowledgeChunk.__table__
    mapping = pipeline.IngestionRunDocument.__table__
    run_values = {
        "id": uuid4(),
        "snapshot_fingerprint": uuid4().hex * 2,
        "execution_token": None,
        "strategy": "fixed",
        "max_tokens": 500,
        "overlap_tokens": 0,
        "embedding_model": pipeline.EMBEDDING_MODEL,
        "status": "completed",
    }
    invalid_run_values = {
        "fingerprint_unique": {"snapshot_fingerprint": result.snapshot_fingerprint},
        "fingerprint_length": {"snapshot_fingerprint": "short"},
        "running_token": {"status": "running", "execution_token": None},
        "status": {"status": "invalid"},
        "strategy": {"strategy": "invalid"},
        "max_tokens": {"max_tokens": 0},
        "negative_overlap": {"overlap_tokens": -1},
        "excess_overlap": {"overlap_tokens": 500},
    }
    with Session(db) as session:
        document = session.exec(
            select(pipeline.KnowledgeDocument).where(
                pipeline.KnowledgeDocument.file_path == "handbook/guide.md"
            )
        ).one()
        document_id = document.id
    if case in invalid_run_values:
        statement = run.insert().values(run_values | invalid_run_values[case])
    elif case in {"path_unique", "document_hash"}:
        statement = doc.insert().values(
            id=uuid4(),
            title="Synthetic",
            content_hash="short" if case == "document_hash" else "a" * 64,
            file_path=(
                "handbook/guide.md" if case == "path_unique" else "handbook/invalid.md"
            ),
        )
    elif case.startswith("mapping") or case == "source_hash":
        statement = mapping.insert().values(
            ingestion_run_id=uuid4() if case == "mapping_run_fk" else result.run_id,
            document_id=uuid4() if case == "mapping_document_fk" else document_id,
            source_hash="short" if case == "source_hash" else "a" * 64,
        )
    elif case == "vector_dimensions":
        statement = text(
            "UPDATE public.knowledge_chunks SET embedding = '[1,2]'::vector"
        )
    else:
        statement = chunk.insert().values(
            id=uuid4(),
            document_id=uuid4() if case == "chunk_document_fk" else document_id,
            ingestion_run_id=(
                None
                if case == "chunk_run_nonnull"
                else uuid4() if case == "chunk_run_fk" else result.run_id
            ),
            chunk_index=(
                -1 if case == "chunk_index" else 0 if case == "chunk_unique" else 1
            ),
            content="Synthetic constraint probe",
            metadata={},
        )
    with pytest.raises(DBAPIError) as error, db.begin() as connection:
        connection.execute(statement)
    assert error.value.orig.pgcode == sqlstate


def test_exact_retrieval_uses_existing_run_and_document_relationships(
    db, pipeline, monkeypatch
):
    """Verify pgvector ranking and joins against the operator-migrated schema."""
    from app.ingestion import retrieval

    documents = _documents(pipeline)
    ingestion = _ingest(pipeline, db, monkeypatch, documents)
    query_vector = [0.25] * 1536

    class FixedEmbedder:
        def embed_texts(self, texts):
            assert texts == ["retrieval question"]
            return [query_vector]

    with Session(db) as session:
        results = retrieval.retrieve_chunks(
            session=session,
            question=" retrieval question ",
            strategy="fixed",
            top_k=5,
            ingestion_run_id=ingestion.run_id,
            embedder=FixedEmbedder(),
        )

    assert len(results) == 1
    result = results[0]
    assert result.similarity_score == pytest.approx(1.0, abs=1e-6)
    assert result.rank == 1
    assert result.strategy == "fixed"
    assert result.content == documents[0].candidates[0].content
    assert result.file_path == documents[0].relative_path
    assert result.title == documents[0].title
    assert result.heading_paths == [["Guide", "Règles"]]
    assert result.source_spans == [[3, 5]]


def test_retrieval_excludes_null_embeddings(db, pipeline, monkeypatch):
    from app.ingestion import retrieval

    documents = _documents(pipeline)
    ingestion = _ingest(pipeline, db, monkeypatch, documents)
    with db.begin() as connection:
        connection.execute(text("UPDATE public.knowledge_chunks SET embedding = NULL"))

    class FixedEmbedder:
        def embed_texts(self, _texts):
            return [[0.25] * 1536]

    with Session(db) as session:
        results = retrieval.retrieve_chunks(
            session=session,
            question="query",
            strategy="fixed",
            ingestion_run_id=ingestion.run_id,
            embedder=FixedEmbedder(),
        )
    assert results == []


def test_retrieval_run_and_strategy_filters_apply_before_top_k(
    db, pipeline, monkeypatch
):
    from app.ingestion import retrieval

    documents = _documents(pipeline)
    fixed_run = _ingest(pipeline, db, monkeypatch, documents)
    changed = [
        replace(
            documents[0],
            candidates=[replace(documents[0].candidates[0], content="other strategy")],
        ),
        documents[1],
    ]
    monkeypatch.setattr(pipeline, "prepare_documents", Mock(return_value=changed))
    with Session(db) as session:
        heading_run_id, token = pipeline._claim_run(
            session,
            uuid4().hex * 2,
            "heading_aware",
            pipeline.ChunkingConfig(500, 0),
        )
        assert token is not None
        vectors = {"other strategy": [0.25] * 1536}
        pipeline._publish_snapshot(session, heading_run_id, token, changed, vectors)

    class FixedEmbedder:
        def embed_texts(self, _texts):
            return [[0.25] * 1536]

    with Session(db) as session:
        results = retrieval.retrieve_chunks(
            session=session,
            question="query",
            strategy="fixed",
            top_k=1,
            ingestion_run_id=fixed_run.run_id,
            embedder=FixedEmbedder(),
        )
    assert [result.content for result in results] == [
        documents[0].candidates[0].content
    ]


def test_retrieval_repeated_query_has_stable_ties_and_top_k(db, pipeline, monkeypatch):
    from app.ingestion import retrieval

    documents = _documents(pipeline)
    original = documents[0]
    candidates = [
        replace(
            original.candidates[0],
            ordinal=index,
            content=f"synthetic retrieval candidate {index}",
        )
        for index in range(3)
    ]
    documents = [replace(original, candidates=candidates), documents[1]]
    ingestion = _ingest(pipeline, db, monkeypatch, documents)

    class FixedEmbedder:
        def embed_texts(self, _texts):
            return [[0.25] * 1536]

    def search():
        with Session(db) as session:
            return retrieval.retrieve_chunks(
                session=session,
                question="same deterministic query",
                strategy="fixed",
                top_k=2,
                ingestion_run_id=ingestion.run_id,
                embedder=FixedEmbedder(),
            )

    first = search()
    second = search()
    assert len(first) == len(second) == 2
    assert [item.chunk_id for item in first] == [item.chunk_id for item in second]
    assert [item.rank for item in first] == [1, 2]
    assert [str(item.chunk_id) for item in first] == sorted(
        str(item.chunk_id) for item in first
    )
    assert first[0].similarity_score == pytest.approx(first[1].similarity_score)
