"""Capture handbook sources and atomically publish fenced ingestion snapshots."""

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, select

from app.core.logger import app_logger
from app.ingestion.chunk_models import ChunkCandidate, ChunkingConfig, ChunkStrategy
from app.ingestion.chunker import chunk_document
from app.ingestion.embeddings import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    MAX_INPUT_TOKENS,
    EmbeddingService,
)
from app.ingestion.markdown_parser import parse_markdown
from app.models.knowledge import (
    IngestionRun,
    IngestionRunDocument,
    KnowledgeChunk,
    KnowledgeDocument,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class IngestionError(ValueError):
    """Public failure code without source content or provider error messages."""

    def __init__(self, reason_code: str, run_id: UUID | None = None) -> None:
        self.reason_code = reason_code
        self.run_id = run_id
        super().__init__(reason_code)


@dataclass(frozen=True)
class PreparedDocument:
    relative_path: str
    source_hash: str
    title: str
    candidates: list[ChunkCandidate]


@dataclass(frozen=True)
class IngestionResult:
    run_id: UUID
    snapshot_fingerprint: str
    skipped: bool
    document_count: int
    chunk_count: int
    reused_embeddings: int
    generated_embeddings: int


def _validate_config(strategy: ChunkStrategy, config: ChunkingConfig) -> None:
    try:
        ChunkingConfig(config.max_tokens, config.overlap_tokens)
    except ValueError:
        raise IngestionError("invalid_chunking_config") from None
    if strategy not in {"fixed", "fixed_overlap", "heading_aware"}:
        raise IngestionError("unknown_strategy")
    if config.max_tokens > MAX_INPUT_TOKENS:
        raise IngestionError("input_token_limit")
    if strategy == "fixed" and config.overlap_tokens:
        raise IngestionError("fixed_requires_zero_overlap")


def prepare_documents(
    source_root: Path,
    strategy: ChunkStrategy,
    config: ChunkingConfig,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> list[PreparedDocument]:
    """Hash and parse the same captured bytes, never reopen a captured file."""
    _validate_config(strategy, config)
    documents: list[PreparedDocument] = []
    try:
        root = source_root.resolve(strict=True)
        repo = repository_root.resolve(strict=True)
        root.relative_to(repo)
        paths = sorted(root.rglob("*.md"))
        for path in paths:
            resolved = path.resolve(strict=True)
            # Do not ingest a symlink outside the configured corpus.
            resolved.relative_to(root)
            if not path.is_file():
                continue
            relative = path.relative_to(repo).as_posix()
            raw = path.read_bytes()
            source_hash = hashlib.sha256(raw).hexdigest()
            parsed = parse_markdown(raw.decode("utf-8"), source_path=relative)
            candidates = chunk_document(parsed, strategy, config)
            documents.append(
                PreparedDocument(relative, source_hash, parsed.title, candidates)
            )
            app_logger.bind(
                file_path=relative,
                source_hash=source_hash,
                candidate_count=len(candidates),
                token_total=sum(item.token_count for item in candidates),
            ).info(
                "ingestion_file_prepared path={} hash={} chunks={} tokens={}",
                relative,
                source_hash,
                len(candidates),
                sum(item.token_count for item in candidates),
            )
    except Exception:
        raise IngestionError("source_processing_failed") from None
    if not documents:
        raise IngestionError("no_source_documents")
    return documents


def candidate_metadata(candidate: ChunkCandidate) -> dict:
    """Preserve candidate provenance using JSON-compatible scalar mappings."""
    return {
        "heading_paths": candidate.heading_paths,
        "source_spans": [asdict(span) for span in candidate.source_spans],
        "parts": [asdict(part) for part in candidate.parts],
        "token_count": candidate.token_count,
        "actual_overlap_tokens": candidate.actual_overlap_tokens,
        "heading_prefix_omitted": candidate.heading_prefix_omitted,
    }


def snapshot_fingerprint(
    documents: Sequence[PreparedDocument],
    strategy: ChunkStrategy,
    config: ChunkingConfig,
) -> str:
    """Exclude incidental IDs, absolute roots, timestamps and execution tokens."""
    payload = {
        "strategy": strategy,
        "max_tokens": config.max_tokens,
        "overlap_tokens": config.overlap_tokens,
        "embedding_model": EMBEDDING_MODEL,
        "dimensions": EMBEDDING_DIMENSIONS,
        "documents": [
            {
                "path": doc.relative_path,
                "source_hash": doc.source_hash,
                "title": doc.title,
                "candidates": [
                    {
                        "ordinal": item.ordinal,
                        "content": item.content,
                        "metadata": candidate_metadata(item),
                    }
                    for item in doc.candidates
                ],
            }
            for doc in sorted(documents, key=lambda doc: doc.relative_path)
        ],
    }
    canonical = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _claim_run(
    session: Session, fingerprint: str, strategy: ChunkStrategy, config: ChunkingConfig
) -> tuple[UUID, UUID | None]:
    token = uuid4()
    proposed_id = uuid4()
    with session.begin():
        statement = (
            insert(IngestionRun)
            .values(
                id=proposed_id,
                snapshot_fingerprint=fingerprint,
                execution_token=token,
                strategy=strategy,
                max_tokens=config.max_tokens,
                overlap_tokens=config.overlap_tokens,
                embedding_model=EMBEDDING_MODEL,
                status="running",
            )
            .on_conflict_do_nothing(index_elements=["snapshot_fingerprint"])
            .returning(IngestionRun.id)
        )
        inserted = session.execute(statement).scalar_one_or_none()
        if inserted is not None:
            return proposed_id, token
        run = session.exec(
            select(IngestionRun)
            .where(IngestionRun.snapshot_fingerprint == fingerprint)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        if run.status == "completed":
            return run.id, None
        if run.status == "running":
            raise IngestionError("run_already_running", run.id)
        if run.status not in {"failed", "pending"}:
            raise IngestionError("invalid_run_status", run.id)
        run.status = "running"
        run.execution_token = token
        session.add(run)
        return run.id, token


def _cached_vectors(session: Session, texts: Sequence[str]) -> dict[str, list[float]]:
    cached: dict[str, list[float]] = {}
    unique = list(dict.fromkeys(texts))
    with session.begin():
        for offset in range(0, len(unique), 256):
            rows = session.exec(
                select(KnowledgeChunk.content, KnowledgeChunk.embedding)
                .join(IngestionRun)
                .where(
                    IngestionRun.status == "completed",
                    IngestionRun.embedding_model == EMBEDDING_MODEL,
                    KnowledgeChunk.content.in_(unique[offset : offset + 256]),  # type: ignore[attr-defined]
                    KnowledgeChunk.embedding.is_not(None),  # type: ignore[union-attr]
                )
                .distinct(KnowledgeChunk.content)
                .order_by(
                    KnowledgeChunk.content,
                    KnowledgeChunk.created_at,
                    KnowledgeChunk.id,
                )
            ).all()
            for content, embedding in rows:
                if embedding is not None:
                    vector = [float(value) for value in embedding]
                    if len(vector) == EMBEDDING_DIMENSIONS and all(
                        math.isfinite(value) for value in vector
                    ):
                        cached.setdefault(content, vector)
    return cached


def _publish_snapshot(
    session: Session,
    run_id: UUID,
    token: UUID,
    documents: Sequence[PreparedDocument],
    vectors: dict[str, list[float]],
) -> None:
    with session.begin():
        run = session.exec(
            select(IngestionRun)
            .where(IngestionRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        if run is None or run.status != "running" or run.execution_token != token:
            app_logger.warning(
                "ingestion_ownership_rejected run={} operation=publish_snapshot reason=execution_ownership_lost",
                run_id,
            )
            raise IngestionError("execution_ownership_lost", run_id)
        # Sorted upserts serialize shared document metadata across distinct runs.
        for doc in sorted(documents, key=lambda doc: doc.relative_path):
            statement = insert(KnowledgeDocument).values(
                id=uuid4(),
                title=doc.title,
                file_path=doc.relative_path,
                content_hash=doc.source_hash,
            )
            statement = statement.on_conflict_do_update(
                index_elements=["file_path"],
                set_={
                    "title": doc.title,
                    "content_hash": doc.source_hash,
                    "updated_at": func.now(),
                },
            ).returning(KnowledgeDocument.id)
            document_id = session.execute(statement).scalar_one()
            session.add(
                IngestionRunDocument(
                    ingestion_run_id=run_id,
                    document_id=document_id,
                    source_hash=doc.source_hash,
                )
            )
            for candidate in doc.candidates:
                headings = candidate.heading_paths
                heading = (
                    headings[0][-1] if len(headings) == 1 and headings[0] else None
                )
                session.add(
                    KnowledgeChunk(
                        document_id=document_id,
                        ingestion_run_id=run_id,
                        chunk_index=candidate.ordinal,
                        content=candidate.content,
                        heading=heading,
                        metadata_=candidate_metadata(candidate),
                        embedding=vectors[candidate.content],
                    )
                )
        run.status = "completed"
        run.execution_token = None
        session.add(run)


def _mark_failed(session: Session, run_id: UUID, token: UUID) -> None:
    with session.begin():
        session.execute(
            update(IngestionRun)
            .where(
                IngestionRun.id == run_id,
                IngestionRun.status == "running",
                IngestionRun.execution_token == token,
            )
            .values(status="failed", execution_token=None)
        )


def ingest_handbook(
    *,
    session: Session,
    source_root: Path,
    strategy: ChunkStrategy,
    config: ChunkingConfig,
    embedder: EmbeddingService,
) -> IngestionResult:
    """Own short transactions on an idle PostgreSQL session; no API call under lock."""
    if session.in_transaction():
        raise IngestionError("session_transaction_active")
    if session.get_bind().dialect.name != "postgresql":
        raise IngestionError("postgresql_required")
    documents = prepare_documents(source_root, strategy, config)
    fingerprint = snapshot_fingerprint(documents, strategy, config)
    texts = [item.content for doc in documents for item in doc.candidates]
    run_id: UUID | None = None
    token: UUID | None = None
    try:
        run_id, token = _claim_run(session, fingerprint, strategy, config)
        if token is None:
            return IngestionResult(
                run_id, fingerprint, True, len(documents), len(texts), 0, 0
            )
        app_logger.bind(run_id=str(run_id), fingerprint=fingerprint).info(
            "ingestion_run_started run={} fingerprint={}", run_id, fingerprint
        )
        vectors = _cached_vectors(session, texts)
        reused = sum(text in vectors for text in texts)
        missing = [text for text in dict.fromkeys(texts) if text not in vectors]
        generated = embedder.embed_texts(missing) if missing else []
        if len(generated) != len(missing) or any(
            len(vector) != EMBEDDING_DIMENSIONS
            or not all(math.isfinite(v) for v in vector)
            for vector in generated
        ):
            raise IngestionError("invalid_embedding_response", run_id)
        vectors.update(zip(missing, generated, strict=True))
        _publish_snapshot(session, run_id, token, documents, vectors)
        result = IngestionResult(
            run_id, fingerprint, False, len(documents), len(texts), reused, len(missing)
        )
        app_logger.bind(**asdict(result)).info(
            "ingestion_run_completed run={} documents={} chunks={} reused={} generated={}",
            run_id,
            result.document_count,
            result.chunk_count,
            result.reused_embeddings,
            result.generated_embeddings,
        )
        return result
    except Exception as error:
        if run_id is not None and token is not None:
            try:
                _mark_failed(session, run_id, token)
            except Exception:
                app_logger.error("ingestion_failure_status_unavailable")
        if isinstance(error, IngestionError):
            raise
        raise IngestionError("ingestion_failed", run_id) from None


def recover_ingestion_run(session: Session, run_id: UUID) -> None:
    """Separate administrative action: revoke ownership, never ingest or retry."""
    if session.in_transaction():
        raise IngestionError("session_transaction_active", run_id)
    if session.get_bind().dialect.name != "postgresql":
        raise IngestionError("postgresql_required", run_id)
    try:
        with session.begin():
            run = session.exec(
                select(IngestionRun)
                .where(IngestionRun.id == run_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).one_or_none()
            if run is None:
                raise IngestionError("run_not_found", run_id)
            if run.status != "running":
                raise IngestionError("run_not_running", run_id)
            run.status = "failed"
            run.execution_token = None
            session.add(run)
    except IngestionError:
        raise
    except Exception:
        raise IngestionError("recovery_failed", run_id) from None
    app_logger.bind(run_id=str(run_id)).warning(
        "ingestion_run_recovered run={}", run_id
    )
