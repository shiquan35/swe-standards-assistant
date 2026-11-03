from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel


class KnowledgeDocument(SQLModel, table=True):
    __tablename__: ClassVar[str] = "knowledge_documents"
    __table_args__ = (
        CheckConstraint(
            "length(content_hash) = 64",
            name="ck_knowledge_documents_content_hash_length",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    title: str = Field(max_length=255, nullable=False)
    file_path: str = Field(sa_column=Column(Text, nullable=False, unique=True))
    content_hash: str = Field(max_length=64, nullable=False)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        ),
    )

    chunks: list["KnowledgeChunk"] = Relationship(
        back_populates="document", cascade_delete=True, passive_deletes=True
    )
    run_documents: list["IngestionRunDocument"] = Relationship(
        back_populates="document", cascade_delete=True, passive_deletes=True
    )


class IngestionRun(SQLModel, table=True):
    __tablename__: ClassVar[str] = "ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            "strategy IN ('fixed', 'fixed_overlap', 'heading_aware')",
            name="ck_ingestion_runs_strategy",
        ),
        CheckConstraint("max_tokens > 0", name="ck_ingestion_runs_max_tokens_positive"),
        CheckConstraint(
            "overlap_tokens >= 0 AND overlap_tokens < max_tokens",
            name="ck_ingestion_runs_overlap_tokens",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_ingestion_runs_status",
        ),
        CheckConstraint(
            "length(snapshot_fingerprint) = 64",
            name="ck_ingestion_runs_snapshot_fingerprint_length",
        ),
        CheckConstraint(
            "status != 'running' OR execution_token IS NOT NULL",
            name="ck_ingestion_runs_running_requires_execution_token",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    snapshot_fingerprint: str = Field(max_length=64, unique=True, nullable=False)
    execution_token: UUID | None = Field(default=None, nullable=True)
    strategy: str = Field(max_length=32, nullable=False)
    max_tokens: int = Field(nullable=False)
    overlap_tokens: int = Field(nullable=False)
    embedding_model: str = Field(max_length=255, nullable=False)
    status: str = Field(default="pending", max_length=16, nullable=False)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        )
    )

    chunks: list["KnowledgeChunk"] = Relationship(
        back_populates="ingestion_run", cascade_delete=True, passive_deletes=True
    )
    documents: list["IngestionRunDocument"] = Relationship(
        back_populates="ingestion_run", cascade_delete=True, passive_deletes=True
    )


class IngestionRunDocument(SQLModel, table=True):
    __tablename__: ClassVar[str] = "ingestion_run_documents"
    __table_args__ = (
        CheckConstraint(
            "length(source_hash) = 64",
            name="ck_ingestion_run_documents_source_hash_length",
        ),
    )

    ingestion_run_id: UUID = Field(
        foreign_key="ingestion_runs.id",
        primary_key=True,
        ondelete="CASCADE",
    )
    document_id: UUID = Field(
        foreign_key="knowledge_documents.id",
        primary_key=True,
        ondelete="CASCADE",
        index=True,
    )
    source_hash: str = Field(max_length=64, nullable=False)

    ingestion_run: IngestionRun = Relationship(back_populates="documents")
    document: KnowledgeDocument = Relationship(back_populates="run_documents")


class KnowledgeChunk(SQLModel, table=True):
    __tablename__: ClassVar[str] = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "ingestion_run_id",
            "chunk_index",
            name="uq_knowledge_chunks_document_run_chunk_index",
        ),
        CheckConstraint("chunk_index >= 0", name="ck_knowledge_chunks_chunk_index"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    document_id: UUID = Field(
        foreign_key="knowledge_documents.id", nullable=False, ondelete="CASCADE"
    )
    ingestion_run_id: UUID = Field(
        foreign_key="ingestion_runs.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    chunk_index: int = Field(ge=0, nullable=False)
    content: str = Field(sa_column=Column(Text, nullable=False))
    heading: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    # SQLAlchemy reserves `metadata`; retain the requested database column name.
    metadata_: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(
            "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
        ),
    )
    embedding: list[float] | None = Field(
        default=None, sa_column=Column(Vector(1536), nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        )
    )

    document: KnowledgeDocument = Relationship(back_populates="chunks")
    ingestion_run: IngestionRun = Relationship(back_populates="chunks")
