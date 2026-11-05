"""Offline pipeline contracts, including SQL intent without database execution.

Run with --confcutdir=tests/ingestion to avoid the application/SQLite fixtures.
Transactional mocks prove orchestration and statement shape, not PostgreSQL
atomicity, isolation, row-lock scheduling, constraints, or cascade behavior.
"""

import hashlib
import importlib
import json
import socket
import sys
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call
from uuid import uuid4

import pytest
from pydantic_settings.sources import DotEnvSettingsSource
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine
from sqlmodel import Session


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs):
        pytest.fail(
            "Pipeline unit tests must not read dotenv or connect to a network/DB"
        )

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(DotEnvSettingsSource, "_read_env_files", forbidden)


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    # The real logger imports settings at import time. Do not initialize either.
    logger_module = ModuleType("app.core.logger")
    logger_module.app_logger = Mock()
    with monkeypatch.context() as imports:
        imports.setitem(sys.modules, "app.core.logger", logger_module)
        module = importlib.import_module("app.ingestion.pipeline")
    monkeypatch.setattr(module, "app_logger", Mock())
    chunker = importlib.import_module("app.ingestion.chunker")

    class Characters:
        def encode(self, text: str) -> list[int]:
            return list(range(len(text)))

    # Exercise real parser/chunker logic without a tiktoken vocabulary download.
    monkeypatch.setattr(chunker, "TiktokenTokenizer", Characters)
    return module


@pytest.fixture
def session() -> Mock:
    """An idle PostgreSQL-shaped Session; every operation is a mock."""
    result = Mock(spec=Session)
    result.get_bind.return_value.dialect.name = "postgresql"
    result.events = []
    result.active = False
    result.in_transaction.side_effect = lambda: result.active

    @contextmanager
    def transaction():
        assert not result.active, "Unexpected nested transaction"
        result.active = True
        result.events.append("begin")
        try:
            yield
        except BaseException:
            result.events.append("rollback")
            raise
        else:
            result.events.append("commit")
        finally:
            result.active = False

    result.begin.side_effect = transaction
    for operation in (result.exec, result.execute, result.add):

        def require_transaction(*_args, _operation=operation, **_kwargs):
            assert result.active, "Persistence must stay inside a short transaction"
            return _operation.return_value

        operation.side_effect = require_transaction
    return result


def candidate(pipeline, content="private chunk", ordinal=0, **changes):
    from app.ingestion.chunk_models import ChunkPart
    from app.ingestion.markdown_models import SourceRange

    values = {
        "ordinal": ordinal,
        "strategy": "heading_aware",
        "content": content,
        "token_count": 12,
        "source_path": "handbook/topic.md",
        "heading_paths": [["Guide", "Rules"]],
        "source_spans": [SourceRange(3, 5)],
        "parts": [ChunkPart(0, len(content), "source", 10, 10 + len(content))],
        "actual_overlap_tokens": 2,
        "heading_prefix_omitted": True,
    }
    values.update(changes)
    return pipeline.ChunkCandidate(**values)


def document(pipeline, path="handbook/topic.md", texts=("private chunk",)):
    return pipeline.PreparedDocument(
        path,
        hashlib.sha256(path.encode()).hexdigest(),
        "Guide",
        [candidate(pipeline, text, i) for i, text in enumerate(texts)],
    )


def run_row(pipeline, status="running", token=None):
    return pipeline.IngestionRun(
        id=uuid4(),
        snapshot_fingerprint="a" * 64,
        execution_token=token if token is not None else uuid4(),
        strategy="fixed",
        max_tokens=500,
        overlap_tokens=0,
        embedding_model=pipeline.EMBEDDING_MODEL,
        status=status,
    )


def compiled(statement):
    return statement.compile(dialect=postgresql.dialect())


@pytest.fixture
def orchestration(pipeline, session, monkeypatch):
    documents = [document(pipeline)]
    state = SimpleNamespace(
        session=session,
        documents=documents,
        run_id=uuid4(),
        token=uuid4(),
        embedder=Mock(spec=pipeline.EmbeddingService),
        config=pipeline.ChunkingConfig(500, 0),
        root=Path("unused-handbook-root"),
    )
    state.prepare = Mock(return_value=documents)
    state.claim = Mock(return_value=(state.run_id, state.token))
    state.cache = Mock(return_value={})
    state.publish = Mock()
    state.fail = Mock()
    state.embedder.embed_texts.return_value = [[0.25] * pipeline.EMBEDDING_DIMENSIONS]
    for name, value in (
        ("prepare_documents", state.prepare),
        ("_claim_run", state.claim),
        ("_cached_vectors", state.cache),
        ("_publish_snapshot", state.publish),
        ("_mark_failed", state.fail),
    ):
        monkeypatch.setattr(pipeline, name, value)

    def ingest():
        return pipeline.ingest_handbook(
            session=session,
            source_root=state.root,
            strategy="fixed",
            config=state.config,
            embedder=state.embedder,
        )

    state.ingest = ingest
    return state


@pytest.mark.parametrize("strategy", ["fixed", "fixed_overlap", "heading_aware"])
def test_prepare_uses_existing_parser_and_all_chunk_strategies(
    pipeline, tmp_path, strategy
):
    root = tmp_path / "handbook"
    root.mkdir()
    raw = "# Café\r\n\r\n## Rules\r\n\r\nRules for naïve teams.\r\n".encode()
    (root / "guide.md").write_bytes(raw)
    config = pipeline.ChunkingConfig(500, 0 if strategy == "fixed" else 20)
    docs = pipeline.prepare_documents(root, strategy, config, repository_root=tmp_path)
    assert len(docs) == 1
    doc = docs[0]
    assert doc.relative_path == "handbook/guide.md"
    assert doc.source_hash == hashlib.sha256(raw).hexdigest()
    assert doc.title == "Café"
    assert doc.candidates
    assert all(item.strategy == strategy for item in doc.candidates)
    assert all(item.source_path == doc.relative_path for item in doc.candidates)
    assert "naïve" in "".join(item.content for item in doc.candidates)


def test_prepare_recurses_sorts_and_includes_readme_and_zero_candidate_files(
    pipeline, tmp_path, monkeypatch
):
    root = tmp_path / "handbook"
    (root / "nested").mkdir(parents=True)
    for name in ("z.md", "nested/b.md", "a.md", "README.md"):
        (root / name).write_text("# Guide\n\n## Rules\n\nBody", encoding="utf-8")
    empty_source = b"# Guide\n\n## Empty\n"
    (root / "empty.md").write_bytes(empty_source)
    (root / "ignored.txt").write_text("not markdown")
    (root / "ignored.MD").write_text("not lowercase markdown")
    (root / "directory.md").mkdir()
    (tmp_path / "outside.md").write_text("not in corpus")
    reads = Mock(wraps=Path.read_bytes)

    def read(path):
        return reads(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    docs = pipeline.prepare_documents(
        root,
        "heading_aware",
        pipeline.ChunkingConfig(500, 20),
        repository_root=tmp_path,
    )
    expected = ["README.md", "a.md", "empty.md", "nested/b.md", "z.md"]
    assert [doc.relative_path for doc in docs] == [
        f"handbook/{name}" for name in expected
    ]
    assert reads.call_args_list == [call(root / name) for name in expected]
    assert docs[2].source_hash == hashlib.sha256(empty_source).hexdigest()
    assert docs[2].candidates == []


def test_prepare_hashes_and_parses_single_capture_despite_file_replacement(
    pipeline, tmp_path, monkeypatch
):
    path = tmp_path / "guide.md"
    captured = b"# Captured\r\n\r\n## Rules\r\n\r\nOriginal body.\r\n"
    path.write_bytes(captured)
    real_read = Path.read_bytes
    read_count = 0

    def read_once(source):
        nonlocal read_count
        read_count += 1
        raw = real_read(source)
        source.write_bytes(b"# Replaced\n\n## Rules\n\nDifferent body.")
        return raw

    parser = Mock(wraps=pipeline.parse_markdown)
    monkeypatch.setattr(Path, "read_bytes", read_once)
    monkeypatch.setattr(pipeline, "parse_markdown", parser)
    doc = pipeline.prepare_documents(
        tmp_path, "fixed", pipeline.ChunkingConfig(500, 0), repository_root=tmp_path
    )[0]
    assert read_count == 1
    parser.assert_called_once_with(captured.decode(), source_path="guide.md")
    assert doc.source_hash == hashlib.sha256(captured).hexdigest()
    assert doc.title == "Captured"
    assert "Original body." in "".join(item.content for item in doc.candidates)
    assert "Different" not in "".join(item.content for item in doc.candidates)


@pytest.mark.parametrize("stage", ["read", "decode", "parse", "chunk"])
def test_prepare_sanitizes_source_failures(pipeline, tmp_path, monkeypatch, stage):
    path = tmp_path / "secret.md"
    path.write_bytes(
        b"\xff" if stage == "decode" else b"# Title\n\n## Rules\n\nPRIVATE SOURCE"
    )
    if stage == "read":
        monkeypatch.setattr(
            Path, "read_bytes", Mock(side_effect=OSError("PRIVATE SOURCE"))
        )
    elif stage in {"parse", "chunk"}:
        monkeypatch.setattr(
            pipeline,
            "parse_markdown" if stage == "parse" else "chunk_document",
            Mock(side_effect=ValueError("PRIVATE SOURCE")),
        )
    with pytest.raises(
        pipeline.IngestionError, match="^source_processing_failed$"
    ) as error:
        pipeline.prepare_documents(
            tmp_path, "fixed", pipeline.ChunkingConfig(500, 0), repository_root=tmp_path
        )
    assert error.value.run_id is None
    assert error.value.__suppress_context__
    assert "PRIVATE" not in str(error.value)
    if stage in {"parse", "chunk"}:
        operation = (
            pipeline.parse_markdown if stage == "parse" else pipeline.chunk_document
        )
        operation.assert_called_once()


@pytest.mark.parametrize(
    "kind", ["empty", "missing", "outside", "symlink_escape", "broken_link"]
)
def test_prepare_rejects_bad_source_scope(pipeline, tmp_path, kind):
    root = tmp_path / "repo" / "handbook"
    root.mkdir(parents=True)
    repo = root.parent
    if kind == "missing":
        root = root / "missing"
    elif kind == "outside":
        root = tmp_path
    elif kind in {"symlink_escape", "broken_link"}:
        target = tmp_path / "outside.md"
        if kind == "symlink_escape":
            target.write_text("private")
        (root / "link.md").symlink_to(target)
    reason = "no_source_documents" if kind == "empty" else "source_processing_failed"
    with pytest.raises(pipeline.IngestionError, match=f"^{reason}$"):
        pipeline.prepare_documents(
            root, "fixed", pipeline.ChunkingConfig(500, 0), repository_root=repo
        )


@pytest.mark.parametrize(
    "strategy, maximum, overlap, reason",
    [
        ("unknown", 500, 0, "unknown_strategy"),
        ("fixed", 500, 1, "fixed_requires_zero_overlap"),
        ("fixed", 8193, 0, "input_token_limit"),
        ("fixed", 0, 0, "invalid_chunking_config"),
        ("fixed", True, 0, "invalid_chunking_config"),
        ("fixed", 2.5, 0, "invalid_chunking_config"),
        ("fixed_overlap", 500, -1, "invalid_chunking_config"),
        ("fixed_overlap", 500, 500, "invalid_chunking_config"),
        ("fixed_overlap", 500, False, "invalid_chunking_config"),
    ],
)
def test_prepare_revalidates_mutable_config_before_source_io(
    pipeline, tmp_path, monkeypatch, strategy, maximum, overlap, reason
):
    config = pipeline.ChunkingConfig(500, 0)
    config.max_tokens, config.overlap_tokens = maximum, overlap
    read = Mock(side_effect=AssertionError("Source must not be read"))
    monkeypatch.setattr(Path, "read_bytes", read)
    with pytest.raises(pipeline.IngestionError, match=f"^{reason}$"):
        pipeline.prepare_documents(tmp_path, strategy, config, repository_root=tmp_path)
    read.assert_not_called()


def test_candidate_metadata_preserves_only_json_provenance(pipeline):
    item = candidate(pipeline)
    expected = {
        "heading_paths": [["Guide", "Rules"]],
        "source_spans": [{"start_line": 3, "end_line": 5}],
        "parts": [
            {
                "output_start": 0,
                "output_end": 13,
                "role": "source",
                "canonical_start": 10,
                "canonical_end": 23,
                "context_kind": None,
            }
        ],
        "token_count": 12,
        "actual_overlap_tokens": 2,
        "heading_prefix_omitted": True,
    }
    metadata = pipeline.candidate_metadata(item)
    assert metadata == expected
    assert json.loads(json.dumps(metadata)) == expected
    assert not {"source_path", "strategy", "content", "ordinal"} & metadata.keys()


def test_fingerprint_canonical_payload_and_document_order(pipeline):
    config = pipeline.ChunkingConfig(500, 100)
    docs = [document(pipeline, "z.md"), document(pipeline, "a.md", ("Café",))]
    payload = {
        "strategy": "heading_aware",
        "max_tokens": 500,
        "overlap_tokens": 100,
        "embedding_model": "text-embedding-3-small",
        "dimensions": 1536,
        "documents": [
            {
                "path": doc.relative_path,
                "source_hash": doc.source_hash,
                "title": doc.title,
                "candidates": [
                    {
                        "ordinal": item.ordinal,
                        "content": item.content,
                        "metadata": pipeline.candidate_metadata(item),
                    }
                    for item in doc.candidates
                ],
            }
            for doc in reversed(docs)
        ],
    }
    expected = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()
    assert pipeline.snapshot_fingerprint(docs, "heading_aware", config) == expected
    assert (
        pipeline.snapshot_fingerprint(list(reversed(docs)), "heading_aware", config)
        == expected
    )
    assert [doc.relative_path for doc in docs] == ["z.md", "a.md"]


@pytest.mark.parametrize(
    "field",
    [
        "path",
        "hash",
        "title",
        "content",
        "ordinal",
        "headings",
        "spans",
        "parts",
        "tokens",
        "overlap",
        "omitted",
        "candidate_order",
        "removed_document",
        "empty_document",
    ],
)
def test_fingerprint_changes_with_every_snapshot_component(pipeline, field):
    docs = [document(pipeline, texts=("one", "two")), document(pipeline, "other.md")]
    config = pipeline.ChunkingConfig(500, 100)
    before = pipeline.snapshot_fingerprint(docs, "heading_aware", config)
    changed = deepcopy(docs)
    doc = changed[0]
    item = doc.candidates[0]
    if field in {"path", "hash", "title"}:
        attribute = {"path": "relative_path", "hash": "source_hash", "title": "title"}[
            field
        ]
        changed[0] = replace(doc, **{attribute: "changed"})
    elif field == "content":
        item.content += "changed"
    elif field == "ordinal":
        item.ordinal += 1
    elif field == "headings":
        item.heading_paths.append(["Other"])
    elif field == "spans":
        item.source_spans[0].end_line += 1
    elif field == "parts":
        item.parts[0].canonical_start += 1
    elif field == "tokens":
        item.token_count += 1
    elif field == "overlap":
        item.actual_overlap_tokens += 1
    elif field == "omitted":
        item.heading_prefix_omitted = not item.heading_prefix_omitted
    elif field == "candidate_order":
        doc.candidates.reverse()
    elif field == "removed_document":
        changed.pop()
    else:
        changed.append(document(pipeline, "empty.md", ()))
    assert pipeline.snapshot_fingerprint(changed, "heading_aware", config) != before


@pytest.mark.parametrize(
    "component", ["strategy", "max_tokens", "overlap_tokens", "model", "dimensions"]
)
def test_fingerprint_changes_with_configuration(pipeline, monkeypatch, component):
    docs = [document(pipeline)]
    config = pipeline.ChunkingConfig(500, 100)
    before = pipeline.snapshot_fingerprint(docs, "heading_aware", config)
    strategy = "heading_aware"
    if component == "strategy":
        strategy = "fixed_overlap"
    elif component in {"max_tokens", "overlap_tokens"}:
        setattr(config, component, getattr(config, component) + 1)
    elif component == "model":
        monkeypatch.setattr(pipeline, "EMBEDDING_MODEL", "different-model")
    else:
        monkeypatch.setattr(pipeline, "EMBEDDING_DIMENSIONS", 32)
    assert pipeline.snapshot_fingerprint(docs, strategy, config) != before


def test_fingerprint_is_independent_of_absolute_root(pipeline, tmp_path):
    snapshots = []
    for name in ("first", "second"):
        repo = tmp_path / name
        (repo / "handbook").mkdir(parents=True)
        (repo / "handbook" / "guide.md").write_bytes(
            b"# Guide\n\n## Rules\n\nSame body"
        )
        snapshots.append(
            pipeline.prepare_documents(
                repo / "handbook",
                "fixed",
                pipeline.ChunkingConfig(500, 0),
                repository_root=repo,
            )
        )
    config = pipeline.ChunkingConfig(500, 0)
    assert pipeline.snapshot_fingerprint(
        snapshots[0], "fixed", config
    ) == pipeline.snapshot_fingerprint(snapshots[1], "fixed", config)


@pytest.mark.parametrize(
    "reason", ["session_transaction_active", "postgresql_required"]
)
def test_ingest_preflight_does_not_prepare_or_claim(pipeline, orchestration, reason):
    state = orchestration
    if reason == "session_transaction_active":
        state.session.active = True
    else:
        state.session.get_bind.return_value.dialect.name = "sqlite"
    with pytest.raises(pipeline.IngestionError, match=f"^{reason}$") as error:
        state.ingest()
    assert error.value.run_id is None
    state.prepare.assert_not_called()
    state.claim.assert_not_called()
    state.fail.assert_not_called()


@pytest.mark.parametrize(
    "reason",
    ["source_processing_failed", "no_source_documents", "invalid_chunking_config"],
)
def test_ingest_prepare_failure_never_creates_run(pipeline, orchestration, reason):
    state = orchestration
    original = pipeline.IngestionError(reason)
    state.prepare.side_effect = original
    with pytest.raises(pipeline.IngestionError) as error:
        state.ingest()
    assert error.value is original
    state.claim.assert_not_called()
    state.cache.assert_not_called()
    state.embedder.embed_texts.assert_not_called()
    state.publish.assert_not_called()
    state.fail.assert_not_called()


def test_identical_completed_snapshot_is_noop_after_preparation(
    pipeline, orchestration
):
    state = orchestration
    state.claim.return_value = state.run_id, None
    result = state.ingest()
    state.prepare.assert_called_once_with(state.root, "fixed", state.config)
    fingerprint = pipeline.snapshot_fingerprint(state.documents, "fixed", state.config)
    state.claim.assert_called_once_with(
        state.session, fingerprint, "fixed", state.config
    )
    assert result == pipeline.IngestionResult(
        state.run_id, fingerprint, True, 1, 1, 0, 0
    )
    state.cache.assert_not_called()
    state.embedder.embed_texts.assert_not_called()
    state.publish.assert_not_called()
    state.fail.assert_not_called()


def test_ingest_reuses_exact_text_and_embeds_unique_misses_in_first_seen_order(
    pipeline, orchestration
):
    state = orchestration
    state.documents[:] = [
        document(pipeline, "a.md", ("cached", "new-b", "cached")),
        document(pipeline, "b.md", ("new-a", "new-b", "Cached")),
    ]
    cached = [0.1] * 1536
    generated = [[value] * 1536 for value in (0.2, 0.3, 0.4)]
    state.cache.return_value = {"cached": cached}

    def embed(texts):
        assert not state.session.in_transaction(), "No API call under transaction/lock"
        assert texts == ["new-b", "new-a", "Cached"]
        return generated

    state.embedder.embed_texts.side_effect = embed
    result = state.ingest()
    state.cache.assert_called_once_with(
        state.session, ["cached", "new-b", "cached", "new-a", "new-b", "Cached"]
    )
    state.embedder.embed_texts.assert_called_once_with(["new-b", "new-a", "Cached"])
    state.publish.assert_called_once_with(
        state.session,
        state.run_id,
        state.token,
        state.documents,
        {
            "cached": cached,
            "new-b": generated[0],
            "new-a": generated[1],
            "Cached": generated[2],
        },
    )
    assert (
        result.document_count,
        result.chunk_count,
        result.reused_embeddings,
        result.generated_embeddings,
    ) == (2, 6, 2, 3)
    assert not result.skipped
    state.fail.assert_not_called()


@pytest.mark.parametrize("empty", [False, True])
def test_ingest_all_cached_or_zero_candidates_does_not_initialize_embedder(
    pipeline, orchestration, empty
):
    state = orchestration
    state.documents[:] = [document(pipeline, texts=() if empty else ("same", "same"))]
    vectors = {} if empty else {"same": [0.5] * 1536}
    state.cache.return_value = vectors
    result = state.ingest()
    state.embedder.embed_texts.assert_not_called()
    state.publish.assert_called_once_with(
        state.session, state.run_id, state.token, state.documents, vectors
    )
    assert (
        result.document_count,
        result.chunk_count,
        result.reused_embeddings,
        result.generated_embeddings,
    ) == (1, 0 if empty else 2, 0 if empty else 2, 0)


@pytest.mark.parametrize("stage", ["claim", "cache", "embed", "publish"])
def test_ingest_failure_fails_only_a_claimed_owner_and_hides_internal_messages(
    pipeline, orchestration, stage
):
    state = orchestration
    operations = {
        "claim": state.claim,
        "cache": state.cache,
        "embed": state.embedder.embed_texts,
        "publish": state.publish,
    }
    operations[stage].side_effect = RuntimeError("PRIVATE SOURCE api-key vector=[1,2]")
    with pytest.raises(pipeline.IngestionError, match="^ingestion_failed$") as error:
        state.ingest()
    assert error.value.run_id == (None if stage == "claim" else state.run_id)
    assert error.value.__suppress_context__
    if stage == "claim":
        state.fail.assert_not_called()
        state.cache.assert_not_called()
    else:
        state.fail.assert_called_once_with(state.session, state.run_id, state.token)
    if stage != "publish":
        state.publish.assert_not_called()
    assert "PRIVATE" not in str(pipeline.app_logger.mock_calls)


def test_embedding_failure_reason_reaches_cli_with_run_id(pipeline, orchestration):
    state = orchestration
    state.embedder.embed_texts.side_effect = pipeline.EmbeddingError("quota_exceeded")
    with pytest.raises(pipeline.IngestionError, match="^quota_exceeded$") as caught:
        state.ingest()
    assert caught.value.run_id == state.run_id
    assert caught.value.__suppress_context__
    state.fail.assert_called_once_with(state.session, state.run_id, state.token)
    state.publish.assert_not_called()


@pytest.mark.parametrize("reason", ["run_already_running", "invalid_run_status"])
def test_claim_rejection_is_preserved_without_failing_another_owner(
    pipeline, orchestration, reason
):
    state = orchestration
    original = pipeline.IngestionError(reason, state.run_id)
    state.claim.side_effect = original
    with pytest.raises(pipeline.IngestionError) as error:
        state.ingest()
    assert error.value is original
    state.fail.assert_not_called()
    state.embedder.embed_texts.assert_not_called()


def test_ownership_loss_preserves_public_error_and_uses_original_token_for_failure(
    pipeline, orchestration
):
    state = orchestration
    original = pipeline.IngestionError("execution_ownership_lost", state.run_id)
    state.publish.side_effect = original
    with pytest.raises(pipeline.IngestionError) as error:
        state.ingest()
    assert error.value is original
    state.fail.assert_called_once_with(state.session, state.run_id, state.token)


def test_failure_status_error_does_not_replace_original_failure(
    pipeline, orchestration
):
    state = orchestration
    original = pipeline.IngestionError("invalid_embedding_response", state.run_id)
    state.embedder.embed_texts.side_effect = original
    state.fail.side_effect = RuntimeError("PRIVATE DB DETAILS")
    with pytest.raises(pipeline.IngestionError) as error:
        state.ingest()
    assert error.value is original
    pipeline.app_logger.error.assert_called_once_with(
        "ingestion_failure_status_unavailable"
    )


@pytest.mark.parametrize(
    "vectors",
    [
        [],
        [[0.0] * 1536] * 2,
        [[]],
        [[0.0] * 1535],
        [[0.0] * 1537],
        [[float("nan")] * 1536],
        [[float("inf")] * 1536],
        [[-float("inf")] * 1536],
    ],
)
def test_invalid_embedding_response_fails_before_publication(
    pipeline, orchestration, vectors
):
    state = orchestration
    state.embedder.embed_texts.return_value = vectors
    with pytest.raises(
        pipeline.IngestionError, match="^invalid_embedding_response$"
    ) as error:
        state.ingest()
    assert error.value.run_id == state.run_id
    state.publish.assert_not_called()
    state.fail.assert_called_once_with(state.session, state.run_id, state.token)


def test_claim_new_run_uses_unique_insert_and_fresh_token(pipeline, session):
    session.execute.return_value.scalar_one_or_none.return_value = uuid4()
    run_id, token = pipeline._claim_run(
        session, "f" * 64, "fixed", pipeline.ChunkingConfig(500, 0)
    )
    statement = compiled(session.execute.call_args.args[0])
    assert "ON CONFLICT (snapshot_fingerprint) DO NOTHING" in str(statement)
    assert "RETURNING ingestion_runs.id" in str(statement)
    assert statement.params == {
        "id": run_id,
        "snapshot_fingerprint": "f" * 64,
        "execution_token": token,
        "strategy": "fixed",
        "max_tokens": 500,
        "overlap_tokens": 0,
        "embedding_model": pipeline.EMBEDDING_MODEL,
        "status": "running",
    }
    assert token is not None
    session.exec.assert_not_called()
    assert session.events == ["begin", "commit"]


@pytest.mark.parametrize(
    "status", ["completed", "running", "failed", "pending", "invalid"]
)
def test_claim_conflict_locks_existing_row_and_branches_by_status(
    pipeline, session, status
):
    row = run_row(pipeline, status)
    old_token = row.execution_token
    session.execute.return_value.scalar_one_or_none.return_value = None
    session.exec.return_value.one.return_value = row
    config = pipeline.ChunkingConfig(500, 0)
    if status in {"running", "invalid"}:
        reason = "run_already_running" if status == "running" else "invalid_run_status"
        with pytest.raises(pipeline.IngestionError, match=f"^{reason}$") as error:
            pipeline._claim_run(session, "a" * 64, "fixed", config)
        assert error.value.run_id == row.id
        assert row.execution_token == old_token
        session.add.assert_not_called()
        assert session.events == ["begin", "rollback"]
    else:
        run_id, token = pipeline._claim_run(session, "a" * 64, "fixed", config)
        assert run_id == row.id
        if status == "completed":
            assert token is None
            session.add.assert_not_called()
        else:
            assert token is not None and token != old_token
            assert row.execution_token == token
            assert row.status == "running"
            session.add.assert_called_once_with(row)
        assert session.events == ["begin", "commit"]
    statement = session.exec.call_args.args[0]
    assert "FOR UPDATE" in str(compiled(statement))
    assert statement.get_execution_options()["populate_existing"] is True
    assert "a" * 64 in compiled(statement).params.values()


def test_cached_vectors_filters_completed_model_and_exact_text_and_validates_vectors(
    pipeline, session
):
    good = [1] * 1536
    rows = [
        ("same", good),
        ("Same", [2.0] * 1536),
        ("same ", [3.0] * 1536),
        ("absent", None),
        ("short", [1.0]),
        ("long", [1.0] * 1537),
        ("nan", [float("nan")] * 1536),
        ("inf", [float("inf")] * 1536),
    ]
    session.exec.return_value.all.return_value = rows
    texts = [content for content, _embedding in rows] + ["same"]
    result = pipeline._cached_vectors(session, texts)
    assert result == {
        "same": [1.0] * 1536,
        "Same": [2.0] * 1536,
        "same ": [3.0] * 1536,
    }
    assert all(type(value) is float for value in result["same"])
    statement = compiled(session.exec.call_args.args[0])
    sql = str(statement)
    assert "JOIN ingestion_runs" in sql
    assert "ingestion_runs.status =" in sql
    assert "ingestion_runs.embedding_model =" in sql
    assert "knowledge_chunks.content IN" in sql
    assert "knowledge_chunks.embedding IS NOT NULL" in sql
    assert (
        "ORDER BY knowledge_chunks.content, knowledge_chunks.created_at, knowledge_chunks.id"
        in sql
    )
    assert "completed" in statement.params.values()
    assert pipeline.EMBEDDING_MODEL in statement.params.values()
    assert list(dict.fromkeys(texts)) in statement.params.values()
    assert session.events == ["begin", "commit"]


def test_cache_query_deduplicates_exact_content_and_selects_only_vector_payload(
    pipeline, session
):
    session.exec.return_value.all.return_value = []
    assert pipeline._cached_vectors(session, ["same", "same", "Same"]) == {}
    session.exec.assert_called_once()
    query = session.exec.call_args.args[0]
    assert list(query.selected_columns) == [
        pipeline.KnowledgeChunk.__table__.c.content,
        pipeline.KnowledgeChunk.__table__.c.embedding,
    ]
    sql = str(compiled(query))
    assert sql.startswith(
        "SELECT DISTINCT ON (knowledge_chunks.content) "
        "knowledge_chunks.content, knowledge_chunks.embedding \nFROM knowledge_chunks"
    )
    assert sql.endswith(
        "ORDER BY knowledge_chunks.content, knowledge_chunks.created_at, knowledge_chunks.id"
    )


@pytest.mark.parametrize(
    "size, batches", [(0, []), (256, [256]), (257, [256, 1]), (513, [256, 256, 1])]
)
def test_cache_batches_unique_inputs_without_writes(pipeline, session, size, batches):
    texts = [f"chunk {i}" for i in range(size)]
    session.exec.return_value.all.return_value = []
    assert pipeline._cached_vectors(session, texts + texts) == {}
    actual = []
    for query in session.exec.call_args_list:
        params = compiled(query.args[0]).params
        actual.append(
            next(value for value in params.values() if isinstance(value, list))
        )
    assert [len(batch) for batch in actual] == batches
    assert [text for batch in actual for text in batch] == texts
    session.add.assert_not_called()
    session.execute.assert_not_called()


@pytest.mark.parametrize(
    "status, token_matches, exists",
    [
        ("failed", True, True),
        ("completed", True, True),
        ("pending", True, True),
        ("running", False, True),
        ("running", True, False),
    ],
)
def test_publish_fences_owner_before_any_snapshot_writes(
    pipeline, session, status, token_matches, exists
):
    token = uuid4()
    row = run_row(pipeline, status, token if token_matches else uuid4())
    session.exec.return_value.one_or_none.return_value = row if exists else None
    with pytest.raises(
        pipeline.IngestionError, match="^execution_ownership_lost$"
    ) as error:
        pipeline._publish_snapshot(session, row.id, token, [document(pipeline)], {})
    assert error.value.run_id == row.id
    session.execute.assert_not_called()
    session.add.assert_not_called()
    statement = session.exec.call_args.args[0]
    assert "FOR UPDATE" in str(compiled(statement))
    assert statement.get_execution_options()["populate_existing"] is True
    assert session.events == ["begin", "rollback"]


def test_publish_upserts_sorted_documents_and_records_zero_candidate_hashes(
    pipeline, session
):
    token = uuid4()
    row = run_row(pipeline, token=token)
    session.exec.return_value.one_or_none.return_value = row
    docs = [document(pipeline, "z.md"), document(pipeline, "a-empty.md", ())]
    empty_id, populated_id = uuid4(), uuid4()
    session.execute.side_effect = [
        Mock(scalar_one=Mock(return_value=empty_id)),
        Mock(scalar_one=Mock(return_value=populated_id)),
    ]
    vector = [0.25] * 1536
    pipeline._publish_snapshot(session, row.id, token, docs, {"private chunk": vector})
    statements = [compiled(query.args[0]) for query in session.execute.call_args_list]
    assert [statement.params["file_path"] for statement in statements] == [
        "a-empty.md",
        "z.md",
    ]
    for statement, doc in zip(statements, reversed(docs), strict=True):
        assert "ON CONFLICT (file_path) DO UPDATE" in str(statement)
        assert "RETURNING knowledge_documents.id" in str(statement)
        assert statement.params["content_hash"] == doc.source_hash
        assert statement.params["title"] == doc.title
        assert "updated_at = now()" in str(statement)
    added = [entry.args[0] for entry in session.add.call_args_list]
    mappings = [
        item for item in added if isinstance(item, pipeline.IngestionRunDocument)
    ]
    assert [
        (item.document_id, item.source_hash, item.ingestion_run_id) for item in mappings
    ] == [
        (empty_id, docs[1].source_hash, row.id),
        (populated_id, docs[0].source_hash, row.id),
    ]
    chunks = [item for item in added if isinstance(item, pipeline.KnowledgeChunk)]
    assert len(chunks) == 1
    chunk = chunks[0]
    assert (chunk.document_id, chunk.ingestion_run_id, chunk.chunk_index) == (
        populated_id,
        row.id,
        0,
    )
    assert chunk.content == "private chunk"
    assert chunk.embedding == vector
    assert chunk.heading == "Rules"
    assert chunk.metadata_ == pipeline.candidate_metadata(docs[0].candidates[0])
    assert added[-1] is row
    assert row.status == "completed" and row.execution_token is None
    assert session.events == ["begin", "commit"]


@pytest.mark.parametrize(
    "headings, expected",
    [([], None), ([[]], None), ([["Only"]], "Only"), ([["A"], ["B"]], None)],
)
def test_publish_legacy_heading_is_set_only_for_one_nonempty_path(
    pipeline, session, headings, expected
):
    row = run_row(pipeline)
    session.exec.return_value.one_or_none.return_value = row
    session.execute.return_value.scalar_one.return_value = uuid4()
    doc = document(pipeline)
    doc.candidates[0].heading_paths = headings
    pipeline._publish_snapshot(
        session, row.id, row.execution_token, [doc], {"private chunk": [0.0] * 1536}
    )
    chunk = next(
        entry.args[0]
        for entry in session.add.call_args_list
        if isinstance(entry.args[0], pipeline.KnowledgeChunk)
    )
    assert chunk.heading == expected


def test_publish_write_failure_rolls_back_without_marking_completed(pipeline, session):
    row = run_row(pipeline)
    token = row.execution_token
    session.exec.return_value.one_or_none.return_value = row
    session.execute.return_value.scalar_one.return_value = uuid4()

    def add(item):
        assert session.active
        if isinstance(item, pipeline.KnowledgeChunk):
            raise RuntimeError("simulated write failure")

    session.add.side_effect = add
    with pytest.raises(RuntimeError, match="simulated write failure"):
        pipeline._publish_snapshot(
            session,
            row.id,
            token,
            [document(pipeline)],
            {"private chunk": [0.0] * 1536},
        )
    assert row.status == "running" and row.execution_token == token
    assert session.events == ["begin", "rollback"]


def test_mark_failed_is_a_single_conditional_owner_and_status_update(pipeline, session):
    run_id, token = uuid4(), uuid4()
    pipeline._mark_failed(session, run_id, token)
    session.execute.assert_called_once()
    statement = compiled(session.execute.call_args.args[0])
    sql = str(statement)
    assert "UPDATE ingestion_runs SET" in sql
    assert "ingestion_runs.id =" in sql
    assert "ingestion_runs.status =" in sql
    assert "ingestion_runs.execution_token =" in sql
    assert run_id in statement.params.values() and token in statement.params.values()
    assert "running" in statement.params.values()
    assert statement.params["status"] == "failed"
    assert statement.params["execution_token"] is None
    session.add.assert_not_called()
    assert session.events == ["begin", "commit"]


@pytest.mark.parametrize(
    "reason", ["session_transaction_active", "postgresql_required"]
)
def test_recover_preflight_never_opens_transaction(pipeline, session, reason):
    run_id = uuid4()
    if reason == "session_transaction_active":
        session.active = True
    else:
        session.get_bind.return_value.dialect.name = "sqlite"
    with pytest.raises(pipeline.IngestionError, match=f"^{reason}$") as error:
        pipeline.recover_ingestion_run(session, run_id)
    assert error.value.run_id == run_id
    session.begin.assert_not_called()


@pytest.mark.parametrize("status", [None, "pending", "failed", "completed"])
def test_recover_rechecks_specified_row_and_refuses_nonrunning(
    pipeline, session, status
):
    row = run_row(pipeline, status or "running")
    token = row.execution_token
    session.exec.return_value.one_or_none.return_value = None if status is None else row
    reason = "run_not_found" if status is None else "run_not_running"
    with pytest.raises(pipeline.IngestionError, match=f"^{reason}$") as error:
        pipeline.recover_ingestion_run(session, row.id)
    assert error.value.run_id == row.id
    session.add.assert_not_called()
    assert row.execution_token == token
    assert session.events == ["begin", "rollback"]


def test_recover_locks_refreshes_and_revokes_token_without_retrying(pipeline, session):
    row = run_row(pipeline)
    session.exec.return_value.one_or_none.return_value = row
    pipeline.recover_ingestion_run(session, row.id)
    statement = session.exec.call_args.args[0]
    assert "FOR UPDATE" in str(compiled(statement))
    assert row.id in compiled(statement).params.values()
    assert statement.get_execution_options()["populate_existing"] is True
    assert row.status == "failed" and row.execution_token is None
    session.add.assert_called_once_with(row)
    session.execute.assert_not_called()
    assert session.events == ["begin", "commit"]


@pytest.mark.parametrize("stage", ["select", "add", "commit"])
def test_recover_sanitizes_database_failures(pipeline, session, stage):
    row = run_row(pipeline)
    session.exec.return_value.one_or_none.return_value = row
    if stage == "select":
        session.exec.side_effect = RuntimeError("PRIVATE DB DETAILS")
    elif stage == "add":
        session.add.side_effect = RuntimeError("PRIVATE DB DETAILS")
    else:

        @contextmanager
        def failed_commit():
            yield
            raise RuntimeError("PRIVATE DB DETAILS")

        session.begin.side_effect = failed_commit
    with pytest.raises(pipeline.IngestionError, match="^recovery_failed$") as error:
        pipeline.recover_ingestion_run(session, row.id)
    assert error.value.run_id == row.id
    assert error.value.__suppress_context__
    pipeline.app_logger.bind.assert_not_called()


def test_recovery_then_retry_fences_the_previous_owner(pipeline, session):
    row = run_row(pipeline)
    original_token = row.execution_token
    session.exec.return_value.one_or_none.return_value = row
    session.exec.return_value.one.return_value = row
    pipeline.recover_ingestion_run(session, row.id)
    assert row.status == "failed" and row.execution_token is None
    session.execute.return_value.scalar_one_or_none.return_value = None
    run_id, new_token = pipeline._claim_run(
        session, row.snapshot_fingerprint, "fixed", pipeline.ChunkingConfig(500, 0)
    )
    assert run_id == row.id and new_token != original_token
    assert row.status == "running" and row.execution_token == new_token
    session.execute.reset_mock()
    session.add.reset_mock()
    with pytest.raises(pipeline.IngestionError, match="^execution_ownership_lost$"):
        pipeline._publish_snapshot(
            session, row.id, original_token, [document(pipeline)], {}
        )
    session.execute.assert_not_called()
    session.add.assert_not_called()
    assert row.status == "running" and row.execution_token == new_token
