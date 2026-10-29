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
    # noqa: F401 ensure model metadata registration

    SQLModel.metadata.create_all(engine)
    yield
    SQLModel.metadata.drop_all(engine)


@pytest.fixture()
def session() -> Generator[Session]:
    with Session(engine) as session:  # type: ignore[arg-type]
        yield session


@pytest.fixture()
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c
