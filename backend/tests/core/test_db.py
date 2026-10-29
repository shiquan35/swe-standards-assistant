"""Smoke test verifying table creation (fixtures live in conftest)."""

from conftest import engine
from sqlalchemy import inspect


def test_database_tables_created():
    inspector = inspect(engine)
    assert "sample" in inspector.get_table_names()
