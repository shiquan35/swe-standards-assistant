"""User database model."""

from datetime import datetime
from typing import ClassVar

import ulid
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    __tablename__: ClassVar[str] = "users"

    id: str = Field(default_factory=lambda: str(ulid.new()), primary_key=True)
    name: str
    email: str
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
