"""Exact cosine retrieval over completed handbook ingestion snapshots."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import cast
from uuid import UUID

from sqlalchemy import Select
from sqlmodel import Session, select

from app.core.logger import app_logger
from app.ingestion.chunk_models import ChunkStrategy
from app.ingestion.embeddings import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    EmbeddingError,
    EmbeddingService,
)
from app.models.knowledge import IngestionRun, KnowledgeChunk, KnowledgeDocument

MAX_TOP_K = 100


class RetrievalError(ValueError):
    """Content-free retrieval failure code safe for diagnostics."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True)
class RetrievalResult:
    chunk_id: UUID
    document_id: UUID
    content: str
    similarity_score: float
    rank: int
    strategy: ChunkStrategy
    tokens: int
    heading_paths: list[list[str]]
    source_spans: list[list[int]]
    file_path: str
    title: str


def _validate_arguments(
    question: object,
    strategy: object,
    top_k: object,
    ingestion_run_id: object,
) -> tuple[str, ChunkStrategy]:
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question_must_be_nonempty_string")
    if not isinstance(strategy, str) or strategy not in {
        "fixed",
        "fixed_overlap",
        "heading_aware",
    }:
        raise ValueError("invalid_strategy")
    if type(top_k) is not int or not 1 <= top_k <= MAX_TOP_K:
        raise ValueError("top_k_out_of_range")
    if ingestion_run_id is not None and not isinstance(ingestion_run_id, UUID):
        raise ValueError("ingestion_run_id_must_be_uuid")
    return question.strip(), cast(ChunkStrategy, strategy)


def _resolve_run(
    session: Session,
    *,
    strategy: ChunkStrategy,
    ingestion_run_id: UUID | None,
) -> IngestionRun | None:
    try:
        if ingestion_run_id is None:
            with session.no_autoflush:
                run = session.exec(
                    select(IngestionRun)
                    .where(
                        IngestionRun.strategy == strategy,
                        IngestionRun.status == "completed",
                    )
                    .order_by(IngestionRun.created_at.desc(), IngestionRun.id.asc())
                    .limit(1)
                ).one_or_none()
            if run is None:
                return None
        else:
            with session.no_autoflush:
                run = session.exec(
                    select(IngestionRun).where(IngestionRun.id == ingestion_run_id)
                ).one_or_none()
            if (
                run is None
                or run.status != "completed"
                or run.strategy != strategy
                or run.embedding_model != EMBEDDING_MODEL
            ):
                app_logger.warning(
                    "retrieval_run_rejected strategy={} run_id={} reason=run_not_searchable",
                    strategy,
                    ingestion_run_id,
                )
                raise RetrievalError("run_not_searchable")
        if run.embedding_model != EMBEDDING_MODEL:
            app_logger.warning(
                "retrieval_run_rejected strategy={} run_id={} reason=run_not_searchable",
                strategy,
                run.id,
            )
            raise RetrievalError("run_not_searchable")
        return run
    except RetrievalError:
        raise
    except Exception:
        app_logger.error(
            "retrieval_failed operation=resolve_run strategy={} run_id={} reason=database_error",
            strategy,
            ingestion_run_id,
        )
        raise RetrievalError("database_error") from None


def _validate_query_vector(vectors: object) -> list[float]:
    if not isinstance(vectors, Sequence) or isinstance(vectors, (str, bytes)):
        raise EmbeddingError("invalid_query_vector")
    if len(vectors) != 1:
        raise EmbeddingError("invalid_query_vector")
    vector = vectors[0]
    if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes)):
        raise EmbeddingError("invalid_query_vector")
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise EmbeddingError("invalid_query_vector")

    normalized: list[float] = []
    has_magnitude = False
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EmbeddingError("invalid_query_vector")
        try:
            number = float(value)
        except (OverflowError, ValueError):
            raise EmbeddingError("invalid_query_vector") from None
        if not math.isfinite(number):
            raise EmbeddingError("invalid_query_vector")
        has_magnitude = has_magnitude or number != 0.0
        normalized.append(number)
    if not has_magnitude:
        raise EmbeddingError("invalid_query_vector")
    return normalized


def _positive_metadata_integer(value: object) -> bool:
    return type(value) is int and value > 0


def _chunk_metadata(metadata: object) -> tuple[int, list[list[str]], list[list[int]]]:
    if not isinstance(metadata, Mapping):
        raise RetrievalError("invalid_chunk_metadata")

    tokens = metadata.get("token_count")
    heading_paths = metadata.get("heading_paths")
    source_spans = metadata.get("source_spans")
    if type(tokens) is not int or tokens < 0:
        raise RetrievalError("invalid_chunk_metadata")
    if not isinstance(heading_paths, list) or any(
        not isinstance(path, list)
        or any(not isinstance(heading, str) for heading in path)
        for path in heading_paths
    ):
        raise RetrievalError("invalid_chunk_metadata")
    if not isinstance(source_spans, list):
        raise RetrievalError("invalid_chunk_metadata")

    spans: list[list[int]] = []
    for span in source_spans:
        if not isinstance(span, Mapping):
            raise RetrievalError("invalid_chunk_metadata")
        start_line = span.get("start_line")
        end_line = span.get("end_line")
        if (
            not _positive_metadata_integer(start_line)
            or not _positive_metadata_integer(end_line)
            or start_line > end_line
        ):
            raise RetrievalError("invalid_chunk_metadata")
        spans.append([start_line, end_line])
    return tokens, [list(path) for path in heading_paths], spans


def _search_statement(
    *, strategy: ChunkStrategy, run_id: UUID, vector: list[float], top_k: int
) -> Select:
    distance = KnowledgeChunk.embedding.cosine_distance(vector)
    return (
        select(
            KnowledgeChunk.id,
            KnowledgeChunk.document_id,
            KnowledgeChunk.content,
            distance.label("cosine_distance"),
            KnowledgeChunk.metadata_,
            KnowledgeDocument.file_path,
            KnowledgeDocument.title,
        )
        .join(KnowledgeDocument)
        .join(IngestionRun)
        .where(
            IngestionRun.id == run_id,
            IngestionRun.strategy == strategy,
            IngestionRun.status == "completed",
            IngestionRun.embedding_model == EMBEDDING_MODEL,
            KnowledgeChunk.ingestion_run_id == run_id,
            KnowledgeChunk.embedding.is_not(None),
        )
        .order_by(distance.asc(), KnowledgeChunk.id.asc())
        .limit(top_k)
    )


def retrieve_chunks(
    *,
    session: Session,
    question: str,
    strategy: ChunkStrategy,
    top_k: int = 5,
    ingestion_run_id: UUID | None = None,
    embedder: EmbeddingService | None = None,
) -> list[RetrievalResult]:
    """Retrieve exact cosine-nearest chunks without taking ownership of session."""
    started = perf_counter()
    normalized_question, normalized_strategy = _validate_arguments(
        question, strategy, top_k, ingestion_run_id
    )
    app_logger.debug(
        "retrieval_started strategy={} top_k={} run_id={} question_chars={} model={}",
        normalized_strategy,
        top_k,
        ingestion_run_id,
        len(normalized_question),
        EMBEDDING_MODEL,
    )

    run = _resolve_run(
        session,
        strategy=normalized_strategy,
        ingestion_run_id=ingestion_run_id,
    )
    if run is None:
        app_logger.debug(
            "retrieval_completed strategy={} run_id=null result_count=0 duration_ms={:.2f}",
            normalized_strategy,
            (perf_counter() - started) * 1000,
        )
        return []

    app_logger.debug(
        "retrieval_run_selected strategy={} run_id={} created_at={} selection={}",
        normalized_strategy,
        run.id,
        run.created_at,
        "explicit" if ingestion_run_id is not None else "latest_completed",
    )
    service = embedder if embedder is not None else EmbeddingService()
    embedding_started = perf_counter()
    try:
        embedded = service.embed_texts([normalized_question])
    except EmbeddingError as error:
        app_logger.error(
            "retrieval_embedding_failed model={} reason={} duration_ms={:.2f}",
            EMBEDDING_MODEL,
            error.reason_code,
            (perf_counter() - embedding_started) * 1000,
        )
        raise
    except Exception:
        app_logger.error(
            "retrieval_embedding_failed model={} reason=embedding_failed duration_ms={:.2f}",
            EMBEDDING_MODEL,
            (perf_counter() - embedding_started) * 1000,
        )
        raise EmbeddingError("embedding_failed") from None
    try:
        vector = _validate_query_vector(embedded)
    except EmbeddingError as error:
        app_logger.error(
            "retrieval_embedding_failed model={} reason={} duration_ms={:.2f}",
            EMBEDDING_MODEL,
            error.reason_code,
            (perf_counter() - embedding_started) * 1000,
        )
        raise

    search_started = perf_counter()
    app_logger.debug(
        "retrieval_vector_query operation=exact_cosine_search operator=cosine_distance strategy={} run_id={} top_k={} embedding_dimensions={}",
        normalized_strategy,
        run.id,
        top_k,
        len(vector),
    )
    try:
        statement = _search_statement(
            strategy=normalized_strategy,
            run_id=run.id,
            vector=vector,
            top_k=top_k,
        )
        with session.no_autoflush:
            rows = session.exec(statement).all()
    except Exception:
        app_logger.error(
            "retrieval_failed operation=vector_search strategy={} run_id={} reason=database_error duration_ms={:.2f}",
            normalized_strategy,
            run.id,
            (perf_counter() - search_started) * 1000,
        )
        raise RetrievalError("database_error") from None
    app_logger.debug(
        "retrieval_vector_query_completed strategy={} run_id={} candidate_count={} duration_ms={:.2f}",
        normalized_strategy,
        run.id,
        len(rows),
        (perf_counter() - search_started) * 1000,
    )

    results: list[RetrievalResult] = []
    for rank, row in enumerate(rows, start=1):
        try:
            chunk_id, document_id, content, distance, metadata, file_path, title = row
            tokens, heading_paths, source_spans = _chunk_metadata(metadata)
            cosine_distance = float(distance)
            if not math.isfinite(cosine_distance):
                raise RetrievalError("database_error")
        except RetrievalError as error:
            if error.reason_code == "invalid_chunk_metadata":
                app_logger.error(
                    "retrieval_failed operation=map_result strategy={} run_id={} rank={} reason={}",
                    normalized_strategy,
                    run.id,
                    rank,
                    error.reason_code,
                )
            raise
        except Exception:
            raise RetrievalError("invalid_chunk_metadata") from None
        results.append(
            RetrievalResult(
                chunk_id=chunk_id,
                document_id=document_id,
                content=content,
                similarity_score=1.0 - cosine_distance,
                rank=rank,
                strategy=normalized_strategy,
                tokens=tokens,
                heading_paths=heading_paths,
                source_spans=source_spans,
                file_path=file_path,
                title=title,
            )
        )

    app_logger.debug(
        "retrieval_completed strategy={} run_id={} result_count={} results={} duration_ms={:.2f}",
        normalized_strategy,
        run.id,
        len(results),
        [
            {
                "chunk_id": str(result.chunk_id),
                "rank": result.rank,
                "similarity_score": result.similarity_score,
            }
            for result in results
        ],
        (perf_counter() - started) * 1000,
    )
    return results
