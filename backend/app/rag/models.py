"""Strict structured-output contracts; validate structure, not factual entailment."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Claim(BaseModel):
    """A model-proposed claim with one or more distinct source references."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    citation_ids: list[UUID] = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("claim_text_must_be_nonblank")
        return value

    @field_validator("citation_ids")
    @classmethod
    def validate_citation_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate_claim_citation_ids")
        return value


class Citation(BaseModel):
    """Application-owned source provenance for a referenced chunk."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID
    title: str | None
    file_path: str | None
    heading_paths: list[list[str]]
    source_spans: list[list[int]]

    @model_validator(mode="after")
    def validate_source_identity(self) -> Self:
        if not (self.title and self.title.strip()) and not (
            self.file_path and self.file_path.strip()
        ):
            raise ValueError("invalid_citation_source")
        return self


class ModelOutput(BaseModel):
    """Generation schema excluding application-owned metadata and run identity.

    Explanatory fields and claim atomicity need semantic generation discipline;
    these validators intentionally make no independent entailment guarantee.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["answered", "partial", "clarification_needed", "abstained"]
    claims: list[Claim]
    clarifying_question: str | None
    reason: str | None
    unanswered_parts: list[str]

    @field_validator("unanswered_parts")
    @classmethod
    def validate_unanswered_parts(cls, value: list[str]) -> list[str]:
        if any(not part.strip() for part in value):
            raise ValueError("unanswered_parts_must_be_nonblank")
        return value

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.status == "abstained":
            if (
                self.claims
                or self.clarifying_question is not None
                or self.unanswered_parts
            ):
                raise ValueError("invalid_abstained_fields")
            if self.reason is None or not self.reason.strip():
                raise ValueError("abstention_reason_must_be_nonblank")
            return self

        if self.reason is not None:
            raise ValueError("reason_requires_abstained_status")
        if self.status == "clarification_needed":
            if self.clarifying_question is None or not self.clarifying_question.strip():
                raise ValueError("clarifying_question_must_be_nonblank")
            return self

        if not self.claims or self.clarifying_question is not None:
            raise ValueError("answer_requires_claims_and_no_clarification")
        if self.status == "answered" and self.unanswered_parts:
            raise ValueError("answered_cannot_have_unanswered_parts")
        if self.status == "partial" and not self.unanswered_parts:
            raise ValueError("partial_requires_unanswered_parts")
        return self


class RagResponse(ModelOutput):
    """Validated outcome with the exact referenced source union and snapshot ID."""

    citations: list[Citation]
    ingestion_run_id: UUID

    @model_validator(mode="after")
    def validate_referenced_sources(self) -> Self:
        referenced_ids = {
            chunk_id for claim in self.claims for chunk_id in claim.citation_ids
        }
        source_ids = [citation.chunk_id for citation in self.citations]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("duplicate_citation_sources")
        if set(source_ids) != referenced_ids:
            raise ValueError("citations_must_equal_referenced_sources")
        return self
