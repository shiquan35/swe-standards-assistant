"""API routes for users."""

from fastapi import APIRouter

from app.core.db import SessionDep
from app.models.user import User
from app.services.user import UserService

router = APIRouter(prefix="/user", tags=["user"])


@router.get("/", response_model=list[User])
def list_users(session: SessionDep) -> list[User]:
    """Return every record in the users table."""
    return UserService.list(session)
