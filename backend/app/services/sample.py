"""Service layer for Sample CRUD.

Separating DB logic from routers keeps endpoints thin & testable.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlmodel import paginate
from sqlmodel import Session, select

from app.models.sample import Sample, SampleCreate, SampleUpdate


class SampleService:
    @staticmethod
    def list(session: Session) -> Page[Sample]:
        statement = select(Sample).order_by(Sample.created_at)
        return paginate(session, statement)

    @staticmethod
    def get(session: Session, *, sample_id: str) -> Sample:
        sample = session.get(Sample, sample_id)
        if not sample:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Sample not found"
            )
        return sample

    @staticmethod
    def create(session: Session, *, data: SampleCreate) -> Sample:
        sample = Sample.model_validate(data)
        session.add(sample)
        session.commit()
        session.refresh(sample)
        return sample

    @staticmethod
    def update(session: Session, *, sample_id: str, data: SampleUpdate) -> Sample:
        sample = SampleService.get(session, sample_id=sample_id)
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(sample, field, value)
        sample.updated_at = datetime.utcnow()
        session.add(sample)
        session.commit()
        session.refresh(sample)
        return sample

    @staticmethod
    def delete(session: Session, *, sample_id: str) -> None:
        sample = SampleService.get(session, sample_id=sample_id)
        session.delete(sample)
        session.commit()
