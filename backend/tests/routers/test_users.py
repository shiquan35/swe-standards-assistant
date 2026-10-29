from collections.abc import Generator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.models.user import User


@pytest.fixture()
def client() -> Generator[TestClient]:
    # Use a valid loopback address so the security middleware accepts test requests.
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        yield test_client


def test_list_users_empty(client: TestClient) -> None:
    response = client.get("/user")

    assert response.status_code == 200
    assert response.json() == []


def test_list_users(client: TestClient, session: Session) -> None:
    users = [
        User(
            id="user-1",
            name="Alice",
            email="alice@example.com",
            created_at=datetime(2026, 1, 1),
        ),
        User(
            id="user-2",
            name="Bob",
            email="bob@example.com",
            created_at=datetime(2026, 1, 2),
        ),
    ]
    session.add_all(users)
    session.commit()

    try:
        response = client.get("/user")

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": "user-1",
                "name": "Alice",
                "email": "alice@example.com",
                "created_at": "2026-01-01T00:00:00",
            },
            {
                "id": "user-2",
                "name": "Bob",
                "email": "bob@example.com",
                "created_at": "2026-01-02T00:00:00",
            },
        ]
    finally:
        for user in users:
            session.delete(user)
        session.commit()
