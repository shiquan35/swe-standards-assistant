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


class KnowledgeChunk(SQLModel, table=True):
    __tablename__: ClassVar[str] = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_knowledge_chunks_document_chunk_index",
        ),
        CheckConstraint("chunk_index >= 0", name="ck_knowledge_chunks_chunk_index"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    document_id: UUID = Field(
        foreign_key="knowledge_documents.id", nullable=False, ondelete="CASCADE"
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
