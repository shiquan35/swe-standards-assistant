from typing import Annotated, TypeAlias

from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine

from app.core.env import env

url = env.DB_FULL_CONNECTION_STRING

connect_args = {"check_same_thread": False}
engine = create_engine(
    url,
    connect_args=connect_args,
    max_overflow=10,  # max overflow pool size (default 10): need more if performing load testing
)


def get_session():
    with Session(engine) as session:
        yield session


# ruff: noqa: UP040
SessionDep: TypeAlias = Annotated[Session, Depends(get_session)]


def init_db() -> None:
    """Create database tables after models are imported.

    Importing models inside this function ensures SQLModel's metadata knows
    about them. Safe to call multiple times.
    """
    from app.models import sample  # noqa: F401
    from app.core.observability import models as _obs_models  # noqa: F401  ← ADD THIS
    SQLModel.metadata.create_all(engine)


if __name__ == "__main__":
    # only run when executing this file directly
    # ! ONLY RUN FOR LOCAL DATABASE
    init_db()
