from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import MedicineRecord

router = APIRouter(prefix="/medicines", tags=["medicines"])


def serialize(record: MedicineRecord) -> dict:
    return {
        "id": record.id,
        "dataset": record.dataset,
        "source_key": record.source_key,
        "code": record.code,
        "name": record.name,
        "dosage": record.dosage,
        "form": record.form,
        "packaging": record.packaging,
        "public_price": record.public_price,
        "reimbursed_price": record.reimbursed_price,
        "manufacturer": record.manufacturer,
        "category": record.category,
        "reimbursement_flag": record.reimbursement_flag,
        "extra_flag": record.extra_flag,
        "source_path": record.source_path,
        "is_active": record.is_active,
        "first_seen_at": record.first_seen_at,
        "last_seen_at": record.last_seen_at,
    }


@router.get("")
def list_medicines(
    dataset: str | None = None,
    active_only: bool = True,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    stmt = select(MedicineRecord)
    if dataset:
        stmt = stmt.where(MedicineRecord.dataset == dataset)
    if active_only:
        stmt = stmt.where(MedicineRecord.is_active.is_(True))
    stmt = stmt.order_by(asc(MedicineRecord.name)).offset(offset).limit(limit)
    records = db.execute(stmt).scalars().all()
    return [serialize(record) for record in records]


@router.get("/search")
def search_medicines(
    q: str,
    dataset: str | None = None,
    active_only: bool = True,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
):
    stmt = select(MedicineRecord).where(
        or_(
            MedicineRecord.name.ilike(f"%{q}%"),
            MedicineRecord.category.ilike(f"%{q}%"),
            MedicineRecord.code.ilike(f"%{q}%"),
        )
    )
    if dataset:
        stmt = stmt.where(MedicineRecord.dataset == dataset)
    if active_only:
        stmt = stmt.where(MedicineRecord.is_active.is_(True))
    stmt = stmt.order_by(asc(MedicineRecord.name)).limit(limit)
    records = db.execute(stmt).scalars().all()
    return [serialize(record) for record in records]


@router.get("/by-source")
def by_source(dataset: str, db: Session = Depends(get_db)):
    records = db.execute(
        select(MedicineRecord).where(MedicineRecord.dataset == dataset).order_by(asc(MedicineRecord.name))
    ).scalars().all()
    return [serialize(record) for record in records]


@router.get("/{medicine_id}")
def get_medicine(medicine_id: int, db: Session = Depends(get_db)):
    record = db.get(MedicineRecord, medicine_id)
    if not record:
        raise HTTPException(status_code=404, detail="Medicine not found")
    return serialize(record)
