"""Offline evaluation contracts; no database, provider, or application settings."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import sys
from collections import deque
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlmodel import Session

from app.evaluation import retrieval as evaluation
from app.ingestion.chunk_models import ChunkStrategy
from app.ingestion.embeddings import EMBEDDING_MODEL, EmbeddingService
from app.models.knowledge import (
    IngestionRun,
    IngestionRunDocument,
    KnowledgeDocument,
)

DIRECT = evaluation.CATEGORIES[0]
INJECTION = evaluation.CATEGORIES[-1]
FIXED = evaluation.Configuration("fixed", 200, 0)
HEADING = evaluation.Configuration("heading_aware", 200, 40)


def fail_runtime(*_args: Any, **_kwargs: Any) -> Any:
    pytest.fail("Unexpected live runtime access")


class RecordingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, tuple[Any, ...]]] = []
        self.bindings: list[dict[str, Any]] = []

    def bind(self, **kwargs: Any) -> RecordingLogger:
        self.bindings.append(kwargs)
        return self

    def info(self, *args: Any) -> None:
        self.events.append(("info", args))

    def debug(self, *args: Any) -> None:
        self.events.append(("debug", args))


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> RecordingLogger:
    # Import the real retrieval result type without importing app settings/logger.
    logger = RecordingLogger()
    module = ModuleType("app.core.logger")
    module.app_logger = logger  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.logger", module)
    runtime = importlib.import_module("app.ingestion.retrieval")
    monkeypatch.setattr(runtime, "retrieve_chunks", fail_runtime)
    monkeypatch.setattr(EmbeddingService, "__init__", fail_runtime)
    return logger


def row(**changes: Any) -> dict[str, Any]:
    return {
        "id": "CASE-1",
        "question": "What must happen before merging?",
        "known_relevant_sources": ["policy.md"],
        "expected_evidence": ["Require tests before merging."],
        "answerable": True,
        "category": DIRECT,
        **changes,
    }


@pytest.fixture
def corpus(tmp_path: Path) -> tuple[Path, Path, Path]:
    handbook = tmp_path / "handbook"
    handbook.mkdir()
    (handbook / "policy.md").write_bytes(
        "# Straße\nRequire tests before merging.\nReview changes.\n".encode()
    )
    (handbook / "other.md").write_text("Unrelated guidance.", encoding="utf-8")
    return tmp_path / "cases.json", handbook, tmp_path


def load(corpus: tuple[Path, Path, Path], rows: Any) -> evaluation.EvaluationInput:
    path, handbook, root = corpus
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return evaluation.load_dataset(path, handbook_root=handbook, repository_root=root)


def error_code(code: str) -> Any:
    return pytest.raises(evaluation.EvaluationError, match=f"^{code}$")


def test_curated_dataset_validates_all_24_cases() -> None:
    dataset = evaluation.load_dataset()
    assert len(dataset.cases) == 24
    assert len({case.id for case in dataset.cases}) == 24
    assert len({case.question.strip() for case in dataset.cases}) == 24
    assert {case.category for case in dataset.cases} == set(evaluation.CATEGORIES)
    assert dataset.dataset_path == evaluation.DEFAULT_DATASET.resolve()
    assert (
        dataset.dataset_sha256
        == hashlib.sha256(evaluation.DEFAULT_DATASET.read_bytes()).hexdigest()
    )
    sources = {
        path.relative_to(evaluation.REPOSITORY_ROOT)
        .as_posix(): hashlib.sha256(path.read_bytes())
        .hexdigest()
        for path in evaluation.HANDBOOK_ROOT.rglob("*.md")
    }
    assert dataset.source_fingerprint == evaluation.source_fingerprint(sources)


def test_dataset_normalizes_evidence_but_preserves_exact_labels(corpus) -> None:
    original = row(expected_evidence=["  REQUIRE\n tests BEFORE merging. ", "STRASSE"])
    dataset = load(corpus, [original])
    case = dataset.cases[0]
    assert case.expected_evidence == tuple(original["expected_evidence"])
    assert case.question == original["question"]
    assert case.known_relevant_sources == ("policy.md",)
    assert dataset.dataset_sha256 == hashlib.sha256(corpus[0].read_bytes()).hexdigest()


@pytest.mark.parametrize("data", [None, {}, [], "text", 3, [None], [[]]])
def test_invalid_dataset_schema(corpus, data) -> None:
    with error_code("invalid_dataset_schema"):
        load(corpus, data)


@pytest.mark.parametrize("field", list(row()))
def test_missing_required_dataset_fields(corpus, field) -> None:
    invalid = row()
    del invalid[field]
    with error_code("invalid_dataset_schema"):
        load(corpus, [invalid])


@pytest.mark.parametrize("field", ["id", "question", "category"])
@pytest.mark.parametrize("value", [None, 42, True, [], "", " \t\n"])
def test_invalid_dataset_strings(corpus, field, value) -> None:
    with error_code("invalid_dataset_string"):
        load(corpus, [row(**{field: value})])


@pytest.mark.parametrize(
    "changes",
    [{"category": "Unknown"}, *({"answerable": v} for v in (0, 1, None, "true"))],
)
def test_invalid_dataset_labels(corpus, changes) -> None:
    with error_code("invalid_dataset_labels"):
        load(corpus, [row(**changes)])


@pytest.mark.parametrize("field", ["known_relevant_sources", "expected_evidence"])
@pytest.mark.parametrize(
    "value", [None, "policy.md", {}, 1, [None], [1], [""], [" \t"]]
)
def test_invalid_dataset_arrays(corpus, field, value) -> None:
    with error_code("invalid_dataset_array"):
        load(corpus, [row(**{field: value})])


@pytest.mark.parametrize(
    "changes",
    [
        {"known_relevant_sources": []},
        {"expected_evidence": []},
        {"answerable": False},
        {"answerable": False, "known_relevant_sources": []},
        {"answerable": False, "expected_evidence": []},
    ],
)
def test_invalid_answerability_labels(corpus, changes) -> None:
    with error_code("invalid_answerability_labels"):
        load(corpus, [row(**changes)])


def test_unanswerable_empty_labels_are_valid(corpus) -> None:
    dataset = load(
        corpus,
        [row(answerable=False, known_relevant_sources=[], expected_evidence=[])],
    )
    assert dataset.cases[0].answerable is False
    assert dataset.cases[0].expected_evidence == ()


@pytest.mark.parametrize(
    "second",
    [
        row(question="Another question"),
        row(id="CASE-2"),
        row(id="CASE-2", question=f"  {row()['question']}\n"),
    ],
)
def test_duplicate_ids_and_trimmed_questions(corpus, second) -> None:
    with error_code("duplicate_case"):
        load(corpus, [row(), second])


@pytest.mark.parametrize(
    "source",
    ["/policy.md", "../policy.md", "nested/../policy.md", "missing.md", "policy.txt"],
)
def test_unsafe_or_missing_source_labels(corpus, source) -> None:
    with error_code("invalid_source_path"):
        load(corpus, [row(known_relevant_sources=[source])])


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_evidence": ["Require tests before merging!"]},
        {"expected_evidence": ["Invented requirement."]},
        {"known_relevant_sources": ["other.md"]},
        {"expected_evidence": ["Require tests before merging.", "Missing statement."]},
    ],
)
def test_evidence_must_occur_in_a_listed_source(corpus, changes) -> None:
    with error_code("evidence_not_in_listed_source"):
        load(corpus, [row(**changes)])


def test_evidence_can_belong_to_different_listed_sources(corpus) -> None:
    dataset = load(
        corpus,
        [
            row(
                known_relevant_sources=["policy.md", "other.md"],
                expected_evidence=[
                    "Require tests before merging.",
                    "Unrelated guidance.",
                ],
            )
        ],
    )
    assert len(dataset.cases[0].expected_evidence) == 2


@pytest.mark.parametrize("raw", [b"{broken", b"\xff", b""])
def test_invalid_dataset_json(corpus, raw) -> None:
    path, handbook, root = corpus
    path.write_bytes(raw)
    with error_code("invalid_dataset_json"):
        evaluation.load_dataset(path, handbook_root=handbook, repository_root=root)


def test_missing_dataset(corpus) -> None:
    path, handbook, root = corpus
    with error_code("invalid_dataset_json"):
        evaluation.load_dataset(path, handbook_root=handbook, repository_root=root)


@pytest.mark.parametrize(
    "problem",
    ["empty", "missing", "invalid_utf8", "escaping_symlink", "outside_repository"],
)
def test_invalid_local_handbook(corpus, problem) -> None:
    path, handbook, root = corpus
    if problem == "empty":
        for source in handbook.iterdir():
            source.unlink()
    elif problem == "missing":
        handbook = root / "absent"
    elif problem == "invalid_utf8":
        (handbook / "policy.md").write_bytes(b"\xff")
    elif problem == "escaping_symlink":
        outside = root / "outside.md"
        outside.write_text("Outside")
        (handbook / "escape.md").symlink_to(outside)
    else:
        root = handbook / "not-the-repository"
    path.write_text(json.dumps([row()]))
    code = "empty_local_sources" if problem == "empty" else "invalid_local_sources"
    with error_code(code):
        evaluation.load_dataset(path, handbook_root=handbook, repository_root=root)


def test_source_fingerprint_uses_canonical_sorted_utf8_json() -> None:
    sources = {"handbook/ß.md": "b" * 64, "handbook/a.md": "a" * 64}
    canonical = json.dumps(
        [{"path": path, "source_hash": sources[path]} for path in sorted(sources)],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    expected = hashlib.sha256(canonical).hexdigest()
    assert evaluation.source_fingerprint(sources) == expected
    assert (
        evaluation.source_fingerprint(dict(reversed(list(sources.items())))) == expected
    )
    for changed in (
        {"renamed.md": "a" * 64},
        {**sources, "extra.md": "c" * 64},
        {**sources, "handbook/a.md": "d" * 64},
    ):
        assert evaluation.source_fingerprint(changed) != expected


def test_local_source_hashes_use_raw_bytes_and_complete_corpus(corpus) -> None:
    first = load(corpus, [row()])
    policy = corpus[1] / "policy.md"
    policy.write_bytes(policy.read_bytes().replace(b"\n", b"\r\n"))
    second = load(corpus, [row()])
    assert first.dataset_sha256 == second.dataset_sha256
    assert first.source_fingerprint != second.source_fingerprint
    (corpus[1] / "other.md").write_text("Changed unlisted source.")
    third = load(corpus, [row()])
    assert second.source_fingerprint != third.source_fingerprint
    corpus[0].write_bytes(corpus[0].read_bytes() + b"\n")
    fourth = evaluation.load_dataset(
        corpus[0], handbook_root=corpus[1], repository_root=corpus[2]
    )
    assert fourth.dataset_sha256 != third.dataset_sha256
    assert fourth.source_fingerprint == third.source_fingerprint


def test_default_and_deduplicated_cartesian_grids() -> None:
    configs, ks = evaluation.expand_configurations()
    assert configs == (
        FIXED,
        evaluation.Configuration("fixed_overlap", 200, 40),
        HEADING,
    )
    assert ks == (3, 5)
    assert len(configs) * len(ks) == 6
    configs, ks = evaluation.expand_configurations(
        ("heading_aware", "fixed", "fixed_overlap", "fixed"),
        (300, 100, 100),
        (40, 0, 40),
        (100, 1, 3, 1),
    )
    expected = {
        evaluation.Configuration(strategy, size, overlap)
        for strategy in evaluation.STRATEGIES
        for size in (100, 300)
        for overlap in ((0,) if strategy == "fixed" else (0, 40))
    }
    assert configs == tuple(sorted(expected))
    assert ks == (1, 3, 100)
    assert len(configs) == 10


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        *[
            ({name: ()}, "empty_configuration")
            for name in ("strategies", "max_tokens", "overlaps", "top_ks")
        ],
        ({"strategies": ("unknown",)}, "invalid_strategy"),
        *[
            ({"max_tokens": (value,)}, "invalid_max_tokens")
            for value in (0, -1, True, 1.5, "200")
        ],
        *[
            ({"top_ks": (value,)}, "invalid_top_k")
            for value in (0, -1, 101, True, 1.5, "3")
        ],
        *[
            ({"overlaps": (value,)}, "invalid_overlap")
            for value in (-1, True, 1.5, "40", 200, 201)
        ],
        ({"max_tokens": (20, 200), "overlaps": (40,)}, "invalid_overlap"),
    ],
)
def test_grid_rejects_empty_invalid_and_boundary_values(kwargs, code) -> None:
    with error_code(code):
        evaluation.expand_configurations(**kwargs)


def test_fixed_grid_forces_zero_and_nonfixed_allows_size_minus_one() -> None:
    assert evaluation.expand_configurations(("fixed",), (1,), (999,), (1,)) == (
        (evaluation.Configuration("fixed", 1, 0),),
        (1,),
    )
    configs, _ = evaluation.expand_configurations(
        ("heading_aware",), (40,), (39,), (100,)
    )
    assert configs == (evaluation.Configuration("heading_aware", 40, 39),)


def test_parse_run_overrides() -> None:
    first, second = uuid4(), uuid4()
    assert evaluation.parse_run_ids([], (FIXED, HEADING)) == {}
    assert evaluation.parse_run_ids(
        [f"{HEADING.label}={second}", f"{FIXED.label}={first}"], (FIXED, HEADING)
    ) == {HEADING: second, FIXED: first}


@pytest.mark.parametrize(
    "value",
    [
        "missing",
        "fixed:200:0=bad",
        "fixed:200:40={id}",
        "fixed:201:0={id}",
        "unknown:200:0={id}",
        "fixed:200:0={id}=extra",
        "fixed:200:0=",
        "= {id}",
    ],
)
def test_invalid_run_override(value) -> None:
    with error_code("invalid_run_mapping"):
        evaluation.parse_run_ids([value.format(id=uuid4())], (FIXED,))


def test_duplicate_run_override_even_with_a_different_uuid() -> None:
    with error_code("duplicate_run_mapping"):
        evaluation.parse_run_ids(
            [f"{FIXED.label}={uuid4()}", f"{FIXED.label}={uuid4()}"], (FIXED,)
        )


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows


class FakeSession:
    """Queue-backed read-only session evaluating the actual equality predicates."""

    def __init__(
        self,
        queue: Sequence[list[Any] | Exception],
        documents: Sequence[KnowledgeDocument] = (),
    ) -> None:
        self.queue = deque(queue)
        self.documents = {document.id: document for document in documents}
        self.statements: list[Any] = []
        self.gets: list[UUID] = []
        self.inside = False
        self.entries = 0

    @property
    @contextmanager
    def no_autoflush(self) -> Iterator[None]:
        assert not self.inside
        self.inside = True
        self.entries += 1
        try:
            yield
        finally:
            self.inside = False

    def exec(self, statement: Any) -> FakeResult:
        assert self.inside
        self.statements.append(statement)
        assert self.queue, "Unexpected database query"
        rows = self.queue.popleft()
        if isinstance(rows, Exception):
            raise rows
        # All production predicates here are column == bound value. Applying
        # them prevents fake rows from bypassing status/model/config/ID filters.
        return FakeResult(
            [
                row
                for row in rows
                if all(
                    getattr(row, clause.left.key) == clause.right.value
                    for clause in statement._where_criteria
                )
            ]
        )

    def get(
        self, model: type[KnowledgeDocument], document_id: UUID
    ) -> KnowledgeDocument | None:
        assert self.inside
        assert model is KnowledgeDocument
        self.gets.append(document_id)
        return self.documents.get(document_id)


def run(config: evaluation.Configuration = FIXED, **changes: Any) -> IngestionRun:
    return IngestionRun(
        **{
            "strategy": config.strategy,
            "max_tokens": config.max_tokens,
            "overlap_tokens": config.overlap_tokens,
            "embedding_model": EMBEDDING_MODEL,
            "status": "completed",
            "snapshot_fingerprint": hashlib.sha256(config.label.encode()).hexdigest(),
            **changes,
        }
    )


def document(path: str = "handbook/policy.md") -> KnowledgeDocument:
    now = datetime.now(UTC)
    return KnowledgeDocument(
        title="Policy",
        file_path=path,
        content_hash="z" * 64,
        created_at=now,
        updated_at=now,
    )


def link(
    selected: IngestionRun, source: KnowledgeDocument, source_hash: str = "a" * 64
) -> IngestionRunDocument:
    return IngestionRunDocument(
        ingestion_run_id=selected.id, document_id=source.id, source_hash=source_hash
    )


def resolve(session: FakeSession, configs=(FIXED,), overrides=None, sources=None):
    return evaluation.resolve_runs(
        cast(Session, session),
        configs,
        overrides or {},
        evaluation.source_fingerprint(
            sources if sources is not None else {"handbook/policy.md": "a" * 64}
        ),
    )


def test_resolve_runs_queries_exact_config_status_model_and_override() -> None:
    selected, other = run(), run()
    source, extra = document(), document("handbook/other.md")
    session = FakeSession(
        [[other, selected], [link(selected, extra, "b" * 64), link(selected, source)]],
        [source, extra],
    )
    assert resolve(
        session,
        overrides={FIXED: selected.id},
        sources={source.file_path: "a" * 64, extra.file_path: "b" * 64},
    ) == {FIXED: selected}
    params = session.statements[0].compile().params
    assert params == {
        "strategy_1": "fixed",
        "max_tokens_1": 200,
        "overlap_tokens_1": 0,
        "status_1": "completed",
        "embedding_model_1": EMBEDDING_MODEL,
        "id_1": selected.id,
    }
    assert session.statements[1].compile().params == {"ingestion_run_id_1": selected.id}
    assert session.gets == [extra.id, source.id]
    assert session.entries == 1 and not session.inside
    assert not session.queue


def test_resolve_distinct_full_snapshots_with_shared_sources() -> None:
    first, second, source = run(), run(HEADING), document()
    session = FakeSession(
        [[first], [link(first, source)], [second], [link(second, source)]], [source]
    )
    assert first.snapshot_fingerprint != second.snapshot_fingerprint
    assert resolve(session, (FIXED, HEADING)) == {FIXED: first, HEADING: second}
    assert "id_1" not in session.statements[0].compile().params
    assert not session.queue


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "pending"},
        {"status": "running"},
        {"status": "failed"},
        {"embedding_model": "unsupported"},
        {"strategy": "heading_aware"},
        {"max_tokens": 300},
        {"overlap_tokens": 40},
        {"id": uuid4()},
    ],
)
def test_explicit_run_must_match_every_query_constraint(changes) -> None:
    requested = uuid4()
    candidate = run(**{"id": requested, **changes})
    session = FakeSession([[candidate]])
    with error_code("run_missing_or_ambiguous"):
        resolve(session, overrides={FIXED: requested})
    assert len(session.statements) == 1
    assert session.gets == []
    assert not session.inside


@pytest.mark.parametrize("candidates", [[], [run(), run()]])
def test_missing_or_ambiguous_automatic_runs(candidates) -> None:
    with error_code("run_missing_or_ambiguous"):
        resolve(FakeSession([candidates]))


@pytest.mark.parametrize(
    "configs, overrides", [((), {}), ((FIXED,), {HEADING: uuid4()})]
)
def test_resolve_invalid_mapping_without_queries(configs, overrides) -> None:
    session = FakeSession([])
    with error_code("invalid_run_mapping"):
        resolve(session, configs, overrides)
    assert session.statements == [] and session.entries == 0


@pytest.mark.parametrize(
    "problem",
    ["missing_document", "duplicate_path", "empty", "hash", "path", "extra_source"],
)
def test_invalid_run_source_mapping(problem) -> None:
    selected, source = run(), document()
    documents = [source]
    links = [link(selected, source)]
    if problem == "missing_document":
        documents = []
    elif problem == "duplicate_path":
        duplicate = document()
        documents.append(duplicate)
        links.append(link(selected, duplicate))
    elif problem == "empty":
        links = []
    elif problem == "hash":
        links = [link(selected, source, "b" * 64)]
    elif problem == "path":
        source.file_path = "handbook/renamed.md"
    else:
        extra = document("handbook/extra.md")
        documents.append(extra)
        links.append(link(selected, extra))
    session = FakeSession([[selected], links], documents)
    code = (
        "invalid_run_sources"
        if problem in ("missing_document", "duplicate_path")
        else "source_snapshot_mismatch"
    )
    with error_code(code):
        resolve(session)
    assert not session.inside


@pytest.mark.parametrize("where", ["run_query", "document_query", "get"])
def test_database_exceptions_are_content_free(monkeypatch, where) -> None:
    selected, source = run(), document()
    secret = RuntimeError("credentials and private SQL")
    queue = (
        [secret]
        if where == "run_query"
        else [
            [selected],
            secret if where == "document_query" else [link(selected, source)],
        ]
    )
    session = FakeSession(queue, [source])
    if where == "get":

        def broken_get(*_args, **_kwargs):
            raise secret

        monkeypatch.setattr(session, "get", broken_get)
    with error_code("database_error") as failure:
        resolve(session)
    assert failure.value.reason_code == "database_error"
    assert "private" not in str(failure.value)
    assert failure.value.__suppress_context__ is True
    assert not session.inside


class FakeEmbedder:
    def __init__(self, response: list[list[float]] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.response = response

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return (
            self.response
            if self.response is not None
            else [[float(len(self.calls)), 0.5]]
        )


def test_cache_exact_text_model_order_and_defensive_vector_copies() -> None:
    delegate = FakeEmbedder()
    cache = evaluation.CachingEmbedder(cast(EmbeddingService, delegate), "model-a")
    texts = [
        "Question",
        "question",
        "Question  text",
        "Question text",
        " Question ",
        "Question",
    ]
    vectors = cache.embed_texts(texts)
    assert delegate.calls == [[text] for text in texts[:-1]]
    assert vectors[0] == vectors[-1] == [1.0, 0.5]
    vectors[0][0] = 999
    assert vectors[-1] == [1.0, 0.5]
    assert cache.embed_texts(["Question"]) == [[1.0, 0.5]]
    cache.model = "model-b"
    assert cache.embed_texts(["Question"]) == [[6.0, 0.5]]
    cache.model = "model-a"
    assert cache.embed_texts(["Question"]) == [[1.0, 0.5]]
    assert len(delegate.calls) == 6
    assert cache.embed_texts([]) == []
    fresh = evaluation.CachingEmbedder(cast(EmbeddingService, delegate), "model-a")
    assert fresh.embed_texts(["Question"]) == [[7.0, 0.5]]


@pytest.mark.parametrize("response", [[], [[1.0], [2.0]]])
def test_cache_rejects_wrong_embedding_count_without_caching(response) -> None:
    delegate = FakeEmbedder(response)
    cache = evaluation.CachingEmbedder(
        cast(EmbeddingService, delegate), EMBEDDING_MODEL
    )
    with error_code("invalid_embedding_response"):
        cache.embed_texts(["Question"])
    assert cache.cache == {}


@pytest.mark.parametrize(
    "problem",
    ["missing_later_run", "ambiguous_later_run", "shared_mismatch", "local_mismatch"],
)
def test_all_run_preflight_precedes_embedding_and_retrieval(corpus, problem) -> None:
    dataset = load(corpus, [row()])
    first, second = run(), run(HEADING)
    source = document("handbook/policy.md")
    other = document("handbook/other.md")
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in corpus[1].glob("*.md")
    }
    links1 = [
        link(first, source, hashes["policy.md"]),
        link(first, other, hashes["other.md"]),
    ]
    links2 = [
        link(second, source, hashes["policy.md"]),
        link(second, other, hashes["other.md"]),
    ]
    if problem == "local_mismatch":
        links1[0].source_hash = "f" * 64
    if problem == "shared_mismatch":
        links2[0].source_hash = "e" * 64
    candidates = (
        []
        if problem == "missing_later_run"
        else [second, run(HEADING)] if problem == "ambiguous_later_run" else [second]
    )
    session = FakeSession([[first], links1, candidates, links2], [source, other])
    delegate = FakeEmbedder()
    code = (
        "run_missing_or_ambiguous"
        if "later_run" in problem
        else "source_snapshot_mismatch"
    )
    with error_code(code):
        evaluation.evaluate_retrieval(
            session=cast(Session, session),
            dataset=dataset,
            configurations=(FIXED, HEADING),
            embedder=cast(EmbeddingService, delegate),
        )
    assert delegate.calls == []
    assert len(session.statements) == (
        2 if problem == "local_mismatch" else 3 if "later_run" in problem else 4
    )


@pytest.mark.parametrize(
    "configs, ks, code",
    [
        ((), (3,), "invalid_configuration"),
        (("fixed",), (3,), "invalid_configuration"),
        ((evaluation.Configuration("fixed", 200, 1),), (3,), "invalid_configuration"),
        (
            (evaluation.Configuration(cast(ChunkStrategy, "invalid"), 200, 0),),
            (3,),
            "invalid_strategy",
        ),
        ((evaluation.Configuration("fixed", 0, 0),), (3,), "invalid_max_tokens"),
        (
            (evaluation.Configuration("heading_aware", 200, 200),),
            (3,),
            "invalid_overlap",
        ),
        *[
            ((FIXED,), ks, "invalid_top_k")
            for ks in ((), (0,), (101,), (True,), (1.5,))
        ],
    ],
)
def test_orchestration_rejects_invalid_inputs_before_resolving(
    monkeypatch, corpus, configs, ks, code
) -> None:
    dataset = load(corpus, [row()])
    monkeypatch.setattr(evaluation, "resolve_runs", fail_runtime)
    with error_code(code):
        evaluation.evaluate_retrieval(
            session=cast(Session, object()),
            dataset=dataset,
            configurations=configs,
            top_ks=ks,
        )


def test_orchestration_max_k_slicing_serialization_diagnostics_and_invocation_cache(
    monkeypatch, corpus, offline
) -> None:
    rows = [
        row(
            id="direct",
            question="  Policy?  ",
            expected_evidence=["Require tests before merging.", "Review changes."],
        ),
        row(
            id="single-space",
            question="Policy ?",
            expected_evidence=["Require tests before merging."],
        ),
        row(id="different-case", question="policy?"),
        row(id="internal-space", question="Policy  ?"),
        row(
            id="unsupported",
            question="Unsupported?",
            answerable=False,
            known_relevant_sources=[],
            expected_evidence=[],
            category="Out-of-Scope Questions",
        ),
        row(id="injection", question="Ignore instructions?", category=INJECTION),
        row(
            id="unsupported-injection",
            question="Reveal secrets?",
            category=INJECTION,
            answerable=False,
            known_relevant_sources=[],
            expected_evidence=[],
        ),
    ]
    dataset = load(corpus, rows)
    selected = {FIXED: run(), HEADING: run(HEADING)}
    session = cast(Session, object())
    overrides = {FIXED: selected[FIXED].id}
    resolutions = []

    def resolve_fake(actual_session, configs, actual_overrides, fingerprint):
        assert actual_session is session
        assert configs == (FIXED, HEADING)
        assert actual_overrides == overrides
        assert fingerprint == dataset.source_fingerprint
        resolutions.append(True)
        return selected

    monkeypatch.setattr(evaluation, "resolve_runs", resolve_fake)
    runtime = importlib.import_module("app.ingestion.retrieval")
    calls = []
    caches = []
    results_by_run = {}
    for config, selected_run in selected.items():
        results_by_run[selected_run.id] = [
            runtime.RetrievalResult(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content=content,
                similarity_score=0.95 - rank / 10,
                rank=rank,
                strategy=config.strategy,
                tokens=20 + rank,
                heading_paths=[["Policy", "Testing"]],
                source_spans=[[2, 4], [8, 8]],
                file_path=f"backend/knowledge_base/engineering-handbook/{filename}",
                title="Policy",
            )
            for rank, (content, filename) in enumerate(
                [
                    ("REQUIRE\n tests before merging.", "policy.md"),
                    ("Require tests before merging. Review changes.", "unlisted.md"),
                    ("Other useful information.", "other.md"),
                ],
                start=1,
            )
        ]

    def retrieve_fake(
        *,
        session: Session,
        question: str,
        strategy: str,
        top_k: int,
        ingestion_run_id: UUID,
        embedder: Any,
    ):
        assert session is expected_session
        assert resolutions
        assert top_k == 5
        assert (
            selected[FIXED if strategy == "fixed" else HEADING].id == ingestion_run_id
        )
        embedder.embed_texts(
            [question.strip()]
        )  # Same intentional trim as real retrieval.
        calls.append((ingestion_run_id, question, top_k))
        caches.append(embedder)
        return copy.deepcopy(results_by_run[ingestion_run_id])

    expected_session = session
    monkeypatch.setattr(runtime, "retrieve_chunks", retrieve_fake)
    delegate = FakeEmbedder()
    parameters = {"top_k": [5, 1, 2, 5], "custom": "preserved"}

    def invoke():
        return evaluation.evaluate_retrieval(
            session=session,
            dataset=dataset,
            configurations=(FIXED, HEADING, FIXED),
            top_ks=(5, 1, 2, 5),
            run_ids=overrides,
            embedder=cast(EmbeddingService, delegate),
            parameters=parameters,
        )

    report = invoke()
    assert len(calls) == len(rows) * 2
    assert calls == [
        (selected[config].id, case.question, 5)
        for config in (FIXED, HEADING)
        for case in dataset.cases
    ]
    unique_inputs = list(dict.fromkeys(case.question.strip() for case in dataset.cases))
    assert delegate.calls == [[text] for text in unique_inputs]
    assert all(cache is caches[0] for cache in caches)
    serialized = json.loads(json.dumps(report))
    metadata = serialized["metadata"]
    UUID(metadata["invocation_id"])
    offset = datetime.fromisoformat(metadata["timestamp"]).utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 0
    assert metadata == {
        "invocation_id": metadata["invocation_id"],
        "timestamp": metadata["timestamp"],
        "dataset_path": str(dataset.dataset_path),
        "dataset_sha256": dataset.dataset_sha256,
        "embedding_model": EMBEDDING_MODEL,
        "source_fingerprint": dataset.source_fingerprint,
        "parameters": parameters,
        "metric_scope": "incomplete-ground-truth evidence coverage",
    }
    assert len(serialized["experiments"]) == 6
    for experiment, (config, cutoff) in zip(
        serialized["experiments"],
        [(config, k) for config in (FIXED, HEADING) for k in (1, 2, 5)],
        strict=True,
    ):
        assert experiment["configuration"] == {
            "strategy": config.strategy,
            "max_tokens": 200,
            "overlap_tokens": config.overlap_tokens,
            "top_k": cutoff,
        }
        assert experiment["run_id"] == str(selected[config].id)
        assert (
            experiment["snapshot_fingerprint"] == selected[config].snapshot_fingerprint
        )
        assert experiment["source_fingerprint"] == dataset.source_fingerprint
        assert experiment["human_hit_at_k"] is None and experiment["human_mrr"] is None
        assert [case["id"] for case in experiment["cases"]] == [
            item["id"] for item in rows
        ]
        for case, original in zip(experiment["cases"], rows, strict=True):
            for key, value in original.items():
                assert case[key] == value
            chunks = case["chunks"]
            assert len(chunks) == min(cutoff, 3)
            assert [chunk["rank"] for chunk in chunks] == list(
                range(1, min(cutoff, 3) + 1)
            )
            assert case["listed_source_matches"] == (
                [] if not original["answerable"] else [1]
            )
            for chunk, actual in zip(
                chunks, results_by_run[selected[config].id], strict=False
            ):
                assert chunk == {
                    "chunk_id": str(actual.chunk_id),
                    "document_id": str(actual.document_id),
                    "content": actual.content,
                    "similarity_score": actual.similarity_score,
                    "rank": actual.rank,
                    "strategy": actual.strategy,
                    "tokens": actual.tokens,
                    "heading_paths": actual.heading_paths,
                    "source_spans": [[2, 4], [8, 8]],
                    "file_path": actual.file_path,
                    "title": actual.title,
                    "relevance": None,
                }
        direct = experiment["cases"][0]
        assert direct["expected_count"] == 2
        assert direct["matched_count"] == (1 if cutoff == 1 else 2)
        assert direct["evidence_hit_at_k"] == 1.0
        assert direct["evidence_recall_at_k"] == (0.5 if cutoff == 1 else 1.0)
        assert direct["evidence_matches"] == [
            {
                "statement": "Require tests before merging.",
                "matching_ranks": [1] if cutoff == 1 else [1, 2],
            },
            {
                "statement": "Review changes.",
                "matching_ranks": [] if cutoff == 1 else [2],
            },
        ]
        metrics = experiment["metrics"]
        assert metrics["eligible_case_count"] == 4
        assert metrics["evidence_hit_at_k"] == 1.0
        assert metrics["macro_evidence_recall_at_k"] == (0.875 if cutoff == 1 else 1.0)
        assert metrics["categories"][DIRECT]["eligible_case_count"] == 4
        assert metrics["categories"][INJECTION] == {
            "eligible_case_count": 0,
            "evidence_hit_at_k": None,
            "macro_evidence_recall_at_k": None,
        }
        assert metrics["diagnostics"] == {
            "unanswerable": {
                "case_count": 2,
                "eligible_case_count": 0,
                "evidence_hit_at_k": None,
                "macro_evidence_recall_at_k": None,
            },
            "prompt_injection": {
                "case_count": 2,
                "eligible_case_count": 1,
                "evidence_hit_at_k": 1.0,
                "macro_evidence_recall_at_k": 1.0,
            },
        }
        for index in (4, 6):
            assert experiment["cases"][index]["chunks"]
            assert experiment["cases"][index]["evidence_hit_at_k"] is None
            assert experiment["cases"][index]["evidence_recall_at_k"] is None
    second = invoke()
    assert (
        cast(dict[str, Any], second["metadata"])["invocation_id"]
        != cast(dict[str, Any], report["metadata"])["invocation_id"]
    )
    assert delegate.calls == [[text] for text in unique_inputs] * 2
    assert caches[len(rows) * 2] is not caches[0]
    assert len(resolutions) == 2
    assert len(offline.bindings) == 2


def test_orchestration_empty_retrieval_and_failure_are_not_partial_reports(
    monkeypatch, corpus
) -> None:
    dataset = load(corpus, [row(), row(id="second", question="Second question?")])
    selected = run()
    monkeypatch.setattr(evaluation, "resolve_runs", lambda *args: {FIXED: selected})
    runtime = importlib.import_module("app.ingestion.retrieval")
    calls = []

    def retrieve_empty(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(runtime, "retrieve_chunks", retrieve_empty)
    report = evaluation.evaluate_retrieval(
        session=cast(Session, object()),
        dataset=dataset,
        configurations=(FIXED,),
        top_ks=(1,),
        embedder=cast(EmbeddingService, FakeEmbedder()),
    )
    experiment = cast(list[dict[str, Any]], report["experiments"])[0]
    assert experiment["metrics"]["eligible_case_count"] == 2
    assert experiment["metrics"]["evidence_hit_at_k"] == 0.0
    assert experiment["metrics"]["macro_evidence_recall_at_k"] == 0.0
    assert all(
        case["chunks"] == [] and case["listed_source_matches"] == []
        for case in experiment["cases"]
    )
    assert len(calls) == 2
    calls.clear()

    def retrieve_failure(**kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise runtime.RetrievalError("database_error")
        return []

    monkeypatch.setattr(runtime, "retrieve_chunks", retrieve_failure)
    with pytest.raises(runtime.RetrievalError, match="^database_error$"):
        evaluation.evaluate_retrieval(
            session=cast(Session, object()),
            dataset=dataset,
            configurations=(FIXED,),
            embedder=cast(EmbeddingService, FakeEmbedder()),
        )
    assert len(calls) == 2
