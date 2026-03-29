from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import RepoUpdate

router = APIRouter(prefix="/updates", tags=["updates"])


def serialize_update(update: RepoUpdate) -> dict[str, Any]:
    return {
        "id": update.id,
        "branch": update.branch,
        "update_kind": update.update_kind,
        "source_name": update.source_name,
        "before_sha": update.before_sha,
        "after_sha": update.after_sha,
        "compare_url": update.compare_url,
        "changed_files": json.loads(update.changed_files_json or "[]"),
        "summary": json.loads(update.summary_json or "{}"),
        "created_at": update.created_at,
    }


@router.get("")
def list_updates(
    limit: int = 20,
    kind: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    stmt = select(RepoUpdate)
    if kind:
        stmt = stmt.where(RepoUpdate.update_kind == kind)
    updates = db.execute(stmt.order_by(desc(RepoUpdate.created_at)).limit(limit)).scalars().all()
    return [serialize_update(update) for update in updates]


@router.get("/latest")
def latest_update(kind: str | None = Query(default=None), db: Session = Depends(get_db)):
    stmt = select(RepoUpdate)
    if kind:
        stmt = stmt.where(RepoUpdate.update_kind == kind)
    update = db.execute(stmt.order_by(desc(RepoUpdate.created_at)).limit(1)).scalar_one_or_none()
    if not update:
        raise HTTPException(status_code=404, detail="No updates ingested yet")
    return serialize_update(update)


@router.get("/{update_id}")
def get_update(update_id: int, db: Session = Depends(get_db)):
    update = db.get(RepoUpdate, update_id)
    if not update:
        raise HTTPException(status_code=404, detail="Update not found")
    return serialize_update(update)
