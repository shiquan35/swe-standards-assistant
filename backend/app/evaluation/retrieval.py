"""Validate evaluation inputs and compare completed, source-identical snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

from app.evaluation.metrics import aggregate_metrics, evidence_metrics, normalize
from app.ingestion.chunk_models import ChunkStrategy

if TYPE_CHECKING:
    from sqlmodel import Session

    from app.ingestion.embeddings import EmbeddingService
    from app.models.knowledge import IngestionRun

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
HANDBOOK_ROOT = REPOSITORY_ROOT / "backend/knowledge_base/engineering-handbook"
DEFAULT_DATASET = REPOSITORY_ROOT / "backend/tests/rag/retrieval_cases.json"
STRATEGIES: tuple[ChunkStrategy, ...] = ("fixed", "fixed_overlap", "heading_aware")
CATEGORIES = (
    "Direct Information Retrieval",
    "Semantic Search",
    "Multi-Section Retrieval",
    "Company-Specific Guidelines",
    "Out-of-Scope Questions",
    "Ambiguous Questions",
    "Hallucination and Unsupported Information",
    "Prompt Injection and Instruction Handling",
)


class EvaluationError(ValueError):
    """Content-free failure code safe to display or log."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    question: str
    known_relevant_sources: tuple[str, ...]
    expected_evidence: tuple[str, ...]
    answerable: bool
    category: str


@dataclass(frozen=True, order=True)
class Configuration:
    strategy: ChunkStrategy
    max_tokens: int
    overlap_tokens: int

    @property
    def label(self) -> str:
        return f"{self.strategy}:{self.max_tokens}:{self.overlap_tokens}"


@dataclass(frozen=True)
class EvaluationInput:
    cases: tuple[EvaluationCase, ...]
    dataset_path: Path
    dataset_sha256: str
    source_fingerprint: str


def expand_configurations(
    strategies: Sequence[str] = STRATEGIES,
    max_tokens: Sequence[int] = (200,),
    overlaps: Sequence[int] = (40,),
    top_ks: Sequence[int] = (3, 5),
) -> tuple[tuple[Configuration, ...], tuple[int, ...]]:
    """Validate and deduplicate the Cartesian grid before runtime access."""
    if not strategies or not max_tokens or not overlaps or not top_ks:
        raise EvaluationError("empty_configuration")
    if any(strategy not in STRATEGIES for strategy in strategies):
        raise EvaluationError("invalid_strategy")
    if any(type(value) is not int or value <= 0 for value in max_tokens):
        raise EvaluationError("invalid_max_tokens")
    if any(type(value) is not int or not 1 <= value <= 100 for value in top_ks):
        raise EvaluationError("invalid_top_k")
    if any(type(value) is not int or value < 0 for value in overlaps):
        raise EvaluationError("invalid_overlap")
    configurations = set()
    for strategy in strategies:
        for size in max_tokens:
            for overlap in (0,) if strategy == "fixed" else overlaps:
                if overlap >= size:
                    raise EvaluationError("invalid_overlap")
                configurations.add(
                    Configuration(cast(ChunkStrategy, strategy), size, overlap)
                )
    return tuple(sorted(configurations)), tuple(sorted(set(top_ks)))


def source_fingerprint(sources: Mapping[str, str]) -> str:
    """Hash the complete sorted path/hash mapping, independent of chunk settings."""
    payload = [{"path": path, "source_hash": sources[path]} for path in sorted(sources)]
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _read_sources(
    root: Path, repository_root: Path
) -> tuple[dict[str, str], dict[str, str]]:
    hashes: dict[str, str] = {}
    contents: dict[str, str] = {}
    try:
        resolved_root = root.resolve(strict=True)
        for path in sorted(resolved_root.rglob("*.md")):
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(resolved_root):
                raise EvaluationError("unsafe_source_path")
            raw = resolved.read_bytes()
            hashes[resolved.relative_to(repository_root.resolve()).as_posix()] = (
                hashlib.sha256(raw).hexdigest()
            )
            contents[path.relative_to(resolved_root).as_posix()] = normalize(
                raw.decode("utf-8")
            )
    except (OSError, UnicodeError, ValueError):
        raise EvaluationError("invalid_local_sources") from None
    if not hashes:
        raise EvaluationError("empty_local_sources")
    return hashes, contents


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise EvaluationError("invalid_dataset_array")
    return tuple(value)


def load_dataset(
    path: Path = DEFAULT_DATASET,
    *,
    handbook_root: Path = HANDBOOK_ROOT,
    repository_root: Path = REPOSITORY_ROOT,
) -> EvaluationInput:
    """Read exact dataset bytes and validate evidence against the local corpus."""
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, ValueError, UnicodeError):
        raise EvaluationError("invalid_dataset_json") from None
    if not isinstance(data, list) or not data:
        raise EvaluationError("invalid_dataset_schema")
    hashes, contents = _read_sources(handbook_root, repository_root)
    cases: list[EvaluationCase] = []
    ids: set[str] = set()
    questions: set[str] = set()
    for row in data:
        if not isinstance(row, dict) or not all(
            key in row
            for key in (
                "id",
                "question",
                "known_relevant_sources",
                "expected_evidence",
                "answerable",
                "category",
            )
        ):
            raise EvaluationError("invalid_dataset_schema")
        case_id, question, category = row["id"], row["question"], row["category"]
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (case_id, question, category)
        ):
            raise EvaluationError("invalid_dataset_string")
        if case_id in ids or question.strip() in questions:
            raise EvaluationError("duplicate_case")
        if category not in CATEGORIES or type(row["answerable"]) is not bool:
            raise EvaluationError("invalid_dataset_labels")
        sources = _string_list(row["known_relevant_sources"])
        evidence = _string_list(row["expected_evidence"])
        if (row["answerable"] and (not sources or not evidence)) or (
            not row["answerable"] and (sources or evidence)
        ):
            raise EvaluationError("invalid_answerability_labels")
        for source in sources:
            relative = Path(source)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or source not in contents
            ):
                raise EvaluationError("invalid_source_path")
        if any(
            not any(normalize(statement) in contents[source] for source in sources)
            for statement in evidence
        ):
            raise EvaluationError("evidence_not_in_listed_source")
        ids.add(case_id)
        questions.add(question.strip())
        cases.append(
            EvaluationCase(
                case_id, question, sources, evidence, row["answerable"], category
            )
        )
    return EvaluationInput(
        tuple(cases),
        path.resolve(),
        hashlib.sha256(raw).hexdigest(),
        source_fingerprint(hashes),
    )


def parse_run_ids(
    values: Sequence[str], configurations: Sequence[Configuration]
) -> dict[Configuration, UUID]:
    """Parse explicit STRATEGY:MAX:OVERLAP=UUID overrides without DB access."""
    allowed = {configuration.label: configuration for configuration in configurations}
    result: dict[Configuration, UUID] = {}
    for value in values:
        try:
            label, raw_id = value.split("=", 1)
            configuration = allowed[label]
            run_id = UUID(raw_id)
        except (ValueError, KeyError):
            raise EvaluationError("invalid_run_mapping") from None
        if configuration in result:
            raise EvaluationError("duplicate_run_mapping")
        result[configuration] = run_id
    return result


def resolve_runs(
    session: Session,
    configurations: Sequence[Configuration],
    overrides: Mapping[Configuration, UUID],
    expected_source_fingerprint: str,
) -> dict[Configuration, IngestionRun]:
    """Preflight every run and its complete source mapping before provider calls."""
    from sqlmodel import select

    from app.ingestion.embeddings import EMBEDDING_MODEL
    from app.models.knowledge import (
        IngestionRun,
        IngestionRunDocument,
        KnowledgeDocument,
    )

    if not configurations or set(overrides) - set(configurations):
        raise EvaluationError("invalid_run_mapping")
    selected: dict[Configuration, IngestionRun] = {}
    try:
        with session.no_autoflush:
            for configuration in configurations:
                statement = select(IngestionRun).where(
                    IngestionRun.strategy == configuration.strategy,
                    IngestionRun.max_tokens == configuration.max_tokens,
                    IngestionRun.overlap_tokens == configuration.overlap_tokens,
                    IngestionRun.status == "completed",
                    IngestionRun.embedding_model == EMBEDDING_MODEL,
                )
                if configuration in overrides:
                    statement = statement.where(
                        IngestionRun.id == overrides[configuration]
                    )
                runs = session.exec(statement).all()
                if len(runs) != 1:
                    raise EvaluationError("run_missing_or_ambiguous")
                run = runs[0]
                documents = session.exec(
                    select(IngestionRunDocument).where(
                        IngestionRunDocument.ingestion_run_id == run.id
                    )
                ).all()
                sources: dict[str, str] = {}
                for document in documents:
                    source = session.get(KnowledgeDocument, document.document_id)
                    if source is None or source.file_path in sources:
                        raise EvaluationError("invalid_run_sources")
                    sources[source.file_path] = document.source_hash
                if (
                    not sources
                    or source_fingerprint(sources) != expected_source_fingerprint
                ):
                    raise EvaluationError("source_snapshot_mismatch")
                selected[configuration] = run
    except EvaluationError:
        raise
    except Exception:
        raise EvaluationError("database_error") from None
    return selected


class CachingEmbedder:
    """One-invocation cache keyed by the model and exact effective API input."""

    def __init__(self, delegate: EmbeddingService, model: str) -> None:
        self.delegate = delegate
        self.model = model
        self.cache: dict[tuple[str, str], list[float]] = {}

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        result: list[list[float]] = []
        for text in texts:
            key = self.model, text
            if key not in self.cache:
                vectors = self.delegate.embed_texts([text])
                if len(vectors) != 1:
                    raise EvaluationError("invalid_embedding_response")
                self.cache[key] = list(vectors[0])
            result.append(list(self.cache[key]))
        return result


def evaluate_retrieval(
    *,
    session: Session,
    dataset: EvaluationInput,
    configurations: Sequence[Configuration],
    top_ks: Sequence[int] = (3, 5),
    run_ids: Mapping[Configuration, UUID] | None = None,
    embedder: EmbeddingService | None = None,
    parameters: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return a complete report; caller owns the session and report persistence."""
    from app.core.logger import app_logger
    from app.ingestion.embeddings import EMBEDDING_MODEL, EmbeddingService
    from app.ingestion.retrieval import retrieve_chunks

    if not configurations or any(
        not isinstance(config, Configuration) for config in configurations
    ):
        raise EvaluationError("invalid_configuration")
    if not top_ks or any(type(k) is not int or not 1 <= k <= 100 for k in top_ks):
        raise EvaluationError("invalid_top_k")
    for config in configurations:
        validated, _ = expand_configurations(
            (config.strategy,), (config.max_tokens,), (config.overlap_tokens,), top_ks
        )
        if config not in validated:
            raise EvaluationError("invalid_configuration")
    configurations = tuple(dict.fromkeys(configurations))
    invocation_id = str(uuid4())
    logger = app_logger.bind(invocation_id=invocation_id)
    logger.info(
        "evaluation_started dataset_sha256={} case_count={} configurations={} top_ks={}",
        dataset.dataset_sha256,
        len(dataset.cases),
        [asdict(config) for config in configurations],
        list(top_ks),
    )
    runs = resolve_runs(
        session, configurations, run_ids or {}, dataset.source_fingerprint
    )
    cache = CachingEmbedder(
        embedder if embedder is not None else EmbeddingService(), EMBEDDING_MODEL
    )
    experiments: list[dict[str, object]] = []
    for configuration in configurations:
        run = runs[configuration]
        logger.info(
            "evaluation_run_selected config={} run_id={} snapshot_fingerprint={} source_fingerprint={} embedding_model={}",
            configuration.label,
            run.id,
            run.snapshot_fingerprint,
            dataset.source_fingerprint,
            EMBEDDING_MODEL,
        )
        by_cutoff: dict[int, list[dict[str, object]]] = {
            k: [] for k in sorted(set(top_ks))
        }
        for case in dataset.cases:
            started = perf_counter()
            logger.debug(
                "evaluation_case_entry case_id={} run_id={} max_top_k={}",
                case.id,
                run.id,
                max(top_ks),
            )
            results = retrieve_chunks(
                session=session,
                question=case.question,
                strategy=configuration.strategy,
                top_k=max(top_ks),
                ingestion_run_id=run.id,
                embedder=cast(EmbeddingService, cache),
            )
            for cutoff, records in by_cutoff.items():
                chunks = results[:cutoff]
                records.append(
                    {
                        **asdict(case),
                        **evidence_metrics(
                            case.expected_evidence,
                            [(chunk.rank, chunk.content) for chunk in chunks],
                        ),
                        "listed_source_matches": [
                            chunk.rank
                            for chunk in chunks
                            if Path(chunk.file_path).name
                            in {
                                Path(source).name
                                for source in case.known_relevant_sources
                            }
                        ],
                        "chunks": [
                            {
                                **asdict(chunk),
                                "chunk_id": str(chunk.chunk_id),
                                "document_id": str(chunk.document_id),
                                "relevance": None,
                            }
                            for chunk in chunks
                        ],
                    }
                )
            logger.debug(
                "evaluation_case_exit case_id={} run_id={} result_ids={} scores={} duration_ms={}",
                case.id,
                run.id,
                [str(chunk.chunk_id) for chunk in results],
                [chunk.similarity_score for chunk in results],
                (perf_counter() - started) * 1000,
            )
        for cutoff, records in by_cutoff.items():
            metrics = aggregate_metrics(records)
            experiments.append(
                {
                    "configuration": {**asdict(configuration), "top_k": cutoff},
                    "run_id": str(run.id),
                    "snapshot_fingerprint": run.snapshot_fingerprint,
                    "source_fingerprint": dataset.source_fingerprint,
                    "metrics": metrics,
                    "human_hit_at_k": None,
                    "human_mrr": None,
                    "cases": records,
                }
            )
            logger.info(
                "evaluation_experiment_completed config={} run_id={} top_k={} metrics={}",
                configuration.label,
                run.id,
                cutoff,
                metrics,
            )
    return {
        "metadata": {
            "invocation_id": invocation_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "dataset_path": str(dataset.dataset_path),
            "dataset_sha256": dataset.dataset_sha256,
            "embedding_model": EMBEDDING_MODEL,
            "source_fingerprint": dataset.source_fingerprint,
            "parameters": dict(parameters or {}),
            "metric_scope": "incomplete-ground-truth evidence coverage",
        },
        "experiments": experiments,
    }
