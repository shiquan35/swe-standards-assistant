"""Database operations for users."""

from sqlmodel import Session, col, select

from app.models.user import User


class UserService:
    @staticmethod
    def list(session: Session) -> list[User]:
        """Return all users in creation order."""
        statement = select(User).order_by(col(User.created_at), col(User.id))
        return list(session.exec(statement).all())
