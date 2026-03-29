from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import WebhookDelivery
from app.services.github_verify import verify_signature
from app.services.ingestion import mark_delivery_status, process_push_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


async def _run_ingestion_task(delivery_id: str, owner: str, repo: str, ref: str, before_sha: str | None, after_sha: str) -> None:
    db: Session = SessionLocal()
    try:
        await process_push_event(db, owner=owner, repo=repo, ref=ref, before_sha=before_sha, after_sha=after_sha)
        await mark_delivery_status(db, delivery_id, "processed")
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Webhook ingestion failed")
        await mark_delivery_status(db, delivery_id, "failed", str(exc))
    finally:
        db.close()


@router.post("/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: str | None = Header(None),
    x_github_delivery: str | None = Header(None),
    x_hub_signature_256: str | None = Header(None),
):
    body = await request.body()
    if not verify_signature(settings.github_webhook_secret, body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(body)
    if x_github_event != "push":
        return {"accepted": False, "reason": "ignored_event"}

    ref = payload.get("ref")
    if ref != settings.target_ref:
        return {"accepted": False, "reason": "ignored_branch", "ref": ref}

    if not x_github_delivery:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Delivery header")

    owner = payload["repository"]["owner"].get("login") or payload["repository"]["owner"].get("name")
    repo = payload["repository"]["name"]
    before_sha = payload.get("before")
    after_sha = payload.get("after")

    db: Session = SessionLocal()
    try:
        existing = db.execute(
            select(WebhookDelivery).where(WebhookDelivery.github_delivery_id == x_github_delivery)
        ).scalar_one_or_none()
        if existing:
            return {"accepted": True, "reason": "duplicate_delivery"}

        delivery = WebhookDelivery(
            github_delivery_id=x_github_delivery,
            event=x_github_event,
            ref=ref,
            before_sha=before_sha,
            after_sha=after_sha,
            payload_json=json.dumps(payload, ensure_ascii=False),
            status="queued",
        )
        db.add(delivery)
        db.commit()
    finally:
        db.close()

    background_tasks.add_task(_run_ingestion_task, x_github_delivery, owner, repo, ref, before_sha, after_sha)
    return {"accepted": True, "delivery_id": x_github_delivery}
