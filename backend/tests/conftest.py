"""Global pytest fixtures for FastAPI application tests.

Sets up an in-memory SQLite database shared across threads via StaticPool
and overrides the application's DB session dependency.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.db import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models.sample import Sample
from app.models.user import User

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def override_get_session() -> Generator[Session]:
    with Session(engine) as session:
        yield session


app.dependency_overrides[get_session] = override_get_session


@pytest.fixture(scope="session", autouse=True)
def create_db_and_tables() -> Generator[None]:
    # Ingestion models use PostgreSQL JSONB/pgvector and have separate tests.
    tables = [Sample.__table__, User.__table__]
    SQLModel.metadata.create_all(engine, tables=tables)
    yield
    SQLModel.metadata.drop_all(engine, tables=tables)


@pytest.fixture()
def session() -> Generator[Session]:
    with Session(engine) as session:  # type: ignore[arg-type]
        yield session


@pytest.fixture()
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c
