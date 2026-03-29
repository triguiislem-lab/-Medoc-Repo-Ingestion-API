from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import IngestedArtifact, MonitoredSource
from app.services.github_client import GitHubClient
from app.services.ingestion import get_last_github_update, ingest_supported_bytes_as_update, process_push_event, record_artifact
from app.services.source_monitors import SOURCES, check_all_sources, check_single_source

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin_key(x_admin_api_key: str | None = Header(None)) -> None:
    if not settings.admin_api_key:
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY is not configured")
    if x_admin_api_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Api-Key header")


@router.post("/reconcile", dependencies=[Depends(require_admin_key)])
async def reconcile(force: bool = False, db: Session = Depends(get_db)):
    gh = GitHubClient(token=settings.github_token)
    latest_commit = await gh.get_latest_branch_commit(settings.repo_owner, settings.repo_name, settings.target_branch)
    latest_sha = latest_commit["sha"]

    last_update = get_last_github_update(db, settings.target_ref)
    before_sha = last_update.after_sha if last_update else None

    if not force and before_sha == latest_sha:
        return {"message": "Already up to date", "sha": latest_sha}

    summary = await process_push_event(
        db,
        owner=settings.repo_owner,
        repo=settings.repo_name,
        ref=settings.target_ref,
        before_sha=before_sha,
        after_sha=latest_sha,
    )
    return {"message": "Reconciliation completed", "summary": summary}


@router.post("/run-source-checks", dependencies=[Depends(require_admin_key)])
async def run_source_checks(db: Session = Depends(get_db)):
    results = await check_all_sources(db)
    return {"message": "Source checks completed", "results": results}


@router.post("/run-source-check/{source_name}", dependencies=[Depends(require_admin_key)])
async def run_source_check(source_name: str, db: Session = Depends(get_db)):
    if source_name not in {source.source_name for source in SOURCES}:
        raise HTTPException(status_code=404, detail="Unknown source")
    result = await check_single_source(db, source_name)
    return {"message": "Source check completed", "result": result}


@router.get("/source-status", dependencies=[Depends(require_admin_key)])
def source_status(db: Session = Depends(get_db)):
    states = db.execute(select(MonitoredSource).order_by(MonitoredSource.source_name.asc())).scalars().all()
    return [
        {
            "id": state.id,
            "source_name": state.source_name,
            "source_url": state.source_url,
            "latest_marker": state.latest_marker,
            "latest_title": state.latest_title,
            "latest_item_url": state.latest_item_url,
            "last_page_hash": state.last_page_hash,
            "last_item_hash": state.last_item_hash,
            "status": state.status,
            "error": state.error,
            "requires_review": state.requires_review,
            "last_checked_at": state.last_checked_at,
            "last_changed_at": state.last_changed_at,
        }
        for state in states
    ]


@router.get("/artifacts", dependencies=[Depends(require_admin_key)])
def list_artifacts(limit: int = 50, db: Session = Depends(get_db)):
    artifacts = db.execute(select(IngestedArtifact).order_by(IngestedArtifact.created_at.desc()).limit(limit)).scalars().all()
    return [
        {
            "id": artifact.id,
            "repo_update_id": artifact.repo_update_id,
            "source_name": artifact.source_name,
            "kind": artifact.kind,
            "title": artifact.title,
            "path": artifact.path,
            "origin_url": artifact.origin_url,
            "storage_path": artifact.storage_path,
            "content_type": artifact.content_type,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "parser_hint": artifact.parser_hint,
            "parse_status": artifact.parse_status,
            "marker": artifact.marker,
            "effective_date_text": artifact.effective_date_text,
            "notes": artifact.notes,
            "created_at": artifact.created_at,
        }
        for artifact in artifacts
    ]


@router.post("/backfills/upload", dependencies=[Depends(require_admin_key)])
async def upload_backfill(
    source_name: str = Form(...),
    parser_hint: str | None = Form(None),
    title: str | None = Form(None),
    origin_url: str | None = Form(None),
    marker: str | None = Form(None),
    effective_date_text: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    parser_hint_clean = parser_hint.lower().strip() if parser_hint else None
    display_title = title or file.filename or "manual-upload"

    if parser_hint_clean:
        try:
            summary = await ingest_supported_bytes_as_update(
                db,
                source_name=source_name,
                title=display_title,
                filename=file.filename or "upload.bin",
                content=content,
                parser_hint=parser_hint_clean,
                origin_url=origin_url,
                marker=marker,
                effective_date_text=effective_date_text,
                notes="Manual backfill upload",
            )
            return {"message": "Backfill uploaded and normalized", "summary": summary}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to parse uploaded file: {exc}") from exc

    artifact = record_artifact(
        db,
        source_name=source_name,
        title=display_title,
        origin_url=origin_url,
        path=Path(file.filename or "upload.bin").name,
        content=content,
        content_type=file.content_type,
        parser_hint=None,
        kind="manual_upload",
        marker=marker,
        effective_date_text=effective_date_text,
        notes="Stored without parser_hint; review required",
        parse_status="review_required",
    )
    return {
        "message": "Backfill uploaded and stored for manual review",
        "artifact": {
            "id": artifact.id,
            "sha256": artifact.sha256,
            "storage_path": artifact.storage_path,
            "parse_status": artifact.parse_status,
        },
    }
