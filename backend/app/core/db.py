from typing import Annotated, TypeAlias

from fastapi import Depends
from sqlmodel import Session, create_engine

from app.core.env import env

url = env.DB_FULL_CONNECTION_STRING

connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
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
