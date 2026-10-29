"""Sample model demonstrating best-practice SQLModel patterns.

This file is intentionally named 'sample' so contributors clearly see it as
an example to copy & adapt (not production-critical code).
"""

from __future__ import annotations

from datetime import datetime

import ulid
from sqlmodel import Field, SQLModel


class SampleBase(SQLModel):
    """Shared fields for create/update/read.

    Fields keep validation constraints small & realistic for demonstration.
    """

    name: str = Field(
        index=True, min_length=1, max_length=255, description="Human friendly name"
    )
    description: str | None = Field(default=None, max_length=1024)
    price: float = Field(gt=0, description="Positive price for example purposes")
    is_active: bool = Field(default=True)


class Sample(SampleBase, table=True):
    """Database table model with ULID primary key.

    ULIDs are lexicographically sortable (time + randomness) and work well as
    string IDs in distributed systems. Stored as TEXT in SQLite.
    """

    id: str = Field(
        default_factory=lambda: str(ulid.new()), primary_key=True, index=True
    )
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class SampleCreate(SampleBase):
    """Payload used when creating a new Sample."""


class SampleRead(SampleBase):
    """Response schema returned to clients."""

    id: str
    created_at: datetime
    updated_at: datetime


class SampleUpdate(SQLModel):
    """Fields allowed for partial update.

    Using `exclude_unset=True` in service layer ensures only provided fields overwrite existing values.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    price: float | None = Field(default=None, gt=0)
    is_active: bool | None = None
