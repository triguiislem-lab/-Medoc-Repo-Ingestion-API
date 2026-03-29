from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import IngestedArtifact, MedicineChange, MedicineRecord, RawSnapshot, RepoUpdate, WebhookDelivery
from app.services.github_client import GitHubClient
from app.services.hashing import sha256_bytes, sha256_text
from app.services.notifier import notify_update
from app.services.parsers import (
    parse_changements,
    parse_html_page_summary,
    parse_latest,
    parse_pct,
    parse_supported_uploaded_bytes,
    parse_vei,
)
from app.services.storage import store_artifact_bytes

logger = logging.getLogger(__name__)

PRIMARY_TARGETS = {"js/latest.json", "js/vei.json", "js/pct.json", "changements.html"}
SUPPORTED_MANUAL_PARSERS = {"latest", "vei", "pct"}
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_relevant(path: str) -> bool:
    if path in PRIMARY_TARGETS:
        return True
    return path.endswith(".html") and "/" not in path and path not in {
        "index.html",
        "404.html",
        "categories.html",
        "pages.html",
        "tags.html",
        "changements.html",
    }


def is_commit_sha(value: str | None) -> bool:
    return bool(value and COMMIT_SHA_RE.fullmatch(value))


def get_last_github_update(db: Session, ref: str) -> RepoUpdate | None:
    return db.execute(
        select(RepoUpdate)
        .where(
            RepoUpdate.update_kind == "github",
            RepoUpdate.branch == ref,
        )
        .order_by(desc(RepoUpdate.created_at))
        .limit(1)
    ).scalar_one_or_none()


async def create_update_if_missing(
    db: Session,
    *,
    branch: str,
    before_sha: str | None,
    after_sha: str,
    compare_url: str | None,
    changed_files: list[str],
    update_kind: str = "github",
    source_name: str | None = None,
) -> RepoUpdate:
    existing = db.execute(
        select(RepoUpdate).where(
            RepoUpdate.update_kind == update_kind,
            RepoUpdate.after_sha == after_sha,
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    update = RepoUpdate(
        branch=branch,
        update_kind=update_kind,
        source_name=source_name,
        before_sha=before_sha,
        after_sha=after_sha,
        compare_url=compare_url,
        changed_files_json=json.dumps(changed_files, ensure_ascii=False),
        summary_json=json.dumps({}, ensure_ascii=False),
    )
    db.add(update)
    db.commit()
    db.refresh(update)
    return update


async def create_synthetic_update(
    db: Session,
    *,
    branch: str,
    compare_url: str | None,
    changed_files: list[str],
    summary: dict[str, Any] | None = None,
    update_kind: str,
    source_name: str,
) -> RepoUpdate:
    after_sha = f"{branch[:18]}-{utcnow().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:12]}"
    update = RepoUpdate(
        branch=branch,
        update_kind=update_kind,
        source_name=source_name,
        before_sha=None,
        after_sha=after_sha,
        compare_url=compare_url,
        changed_files_json=json.dumps(changed_files, ensure_ascii=False),
        summary_json=json.dumps(summary or {}, ensure_ascii=False),
    )
    db.add(update)
    db.commit()
    db.refresh(update)
    return update


def save_snapshot(db: Session, update_id: int, path: str, file_sha: str | None, content: str, content_type: str | None = None) -> None:
    existing = db.execute(select(RawSnapshot).where(RawSnapshot.update_id == update_id, RawSnapshot.path == path)).scalar_one_or_none()
    if existing:
        existing.file_sha = file_sha
        existing.content = content
        existing.content_type = content_type
        existing.fetched_at = utcnow()
    else:
        db.add(
            RawSnapshot(
                update_id=update_id,
                path=path,
                file_sha=file_sha,
                content=content,
                content_type=content_type,
            )
        )
    db.commit()


def record_artifact(
    db: Session,
    *,
    source_name: str,
    title: str | None,
    origin_url: str | None,
    path: str | None,
    content: bytes,
    content_type: str | None,
    parser_hint: str | None,
    kind: str = "file",
    repo_update_id: int | None = None,
    monitored_source_id: int | None = None,
    marker: str | None = None,
    effective_date_text: str | None = None,
    notes: str | None = None,
    parse_status: str = "stored",
) -> IngestedArtifact:
    sha256 = sha256_bytes(content)
    existing = db.execute(select(IngestedArtifact).where(IngestedArtifact.source_name == source_name, IngestedArtifact.sha256 == sha256)).scalar_one_or_none()
    if existing:
        return existing

    filename = Path(path or title or "artifact.bin").name
    storage_path = store_artifact_bytes(source_name, filename, content, content_type=content_type)
    artifact = IngestedArtifact(
        repo_update_id=repo_update_id,
        monitored_source_id=monitored_source_id,
        source_name=source_name,
        kind=kind,
        title=title,
        path=path,
        origin_url=origin_url,
        storage_path=storage_path,
        content_type=content_type,
        sha256=sha256,
        size_bytes=len(content),
        parser_hint=parser_hint,
        parse_status=parse_status,
        marker=marker,
        effective_date_text=effective_date_text,
        notes=notes,
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return artifact


def comparable_payload(medicine: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": medicine.get("code"),
        "name": medicine.get("name"),
        "dosage": medicine.get("dosage"),
        "form": medicine.get("form"),
        "packaging": medicine.get("packaging"),
        "public_price": medicine.get("public_price"),
        "reimbursed_price": medicine.get("reimbursed_price"),
        "manufacturer": medicine.get("manufacturer"),
        "category": medicine.get("category"),
        "reimbursement_flag": medicine.get("reimbursement_flag"),
        "extra_flag": medicine.get("extra_flag"),
    }


def upsert_medicines(db: Session, update: RepoUpdate, dataset: str, items: list[Any]) -> dict[str, int]:
    added = updated = unchanged = 0
    seen_keys: set[str] = set()

    for item in items:
        payload = asdict(item)
        seen_keys.add(item.source_key)
        record = db.execute(
            select(MedicineRecord).where(MedicineRecord.dataset == dataset, MedicineRecord.source_key == item.source_key)
        ).scalar_one_or_none()

        if record is None:
            record = MedicineRecord(
                dataset=item.dataset,
                source_key=item.source_key,
                code=item.code,
                name=item.name,
                dosage=item.dosage,
                form=item.form,
                packaging=item.packaging,
                public_price=item.public_price,
                reimbursed_price=item.reimbursed_price,
                manufacturer=item.manufacturer,
                category=item.category,
                reimbursement_flag=item.reimbursement_flag,
                extra_flag=item.extra_flag,
                source_path=item.source_path,
                raw_json=json.dumps(payload, ensure_ascii=False),
                first_seen_update_id=update.id,
                last_seen_update_id=update.id,
                first_seen_at=utcnow(),
                last_seen_at=utcnow(),
                is_active=True,
            )
            db.add(record)
            db.flush()
            db.add(
                MedicineChange(
                    update_id=update.id,
                    dataset=dataset,
                    source_key=item.source_key,
                    medicine_record_id=record.id,
                    change_type="added",
                    before_json=None,
                    after_json=json.dumps(payload, ensure_ascii=False),
                )
            )
            added += 1
            continue

        before = json.loads(record.raw_json)
        new_comp = comparable_payload(payload)
        old_comp = comparable_payload(before)

        if new_comp != old_comp or not record.is_active:
            record.code = item.code
            record.name = item.name
            record.dosage = item.dosage
            record.form = item.form
            record.packaging = item.packaging
            record.public_price = item.public_price
            record.reimbursed_price = item.reimbursed_price
            record.manufacturer = item.manufacturer
            record.category = item.category
            record.reimbursement_flag = item.reimbursement_flag
            record.extra_flag = item.extra_flag
            record.source_path = item.source_path
            record.raw_json = json.dumps(payload, ensure_ascii=False)
            record.last_seen_update_id = update.id
            record.last_seen_at = utcnow()
            record.is_active = True
            db.add(
                MedicineChange(
                    update_id=update.id,
                    dataset=dataset,
                    source_key=item.source_key,
                    medicine_record_id=record.id,
                    change_type="updated",
                    before_json=json.dumps(before, ensure_ascii=False),
                    after_json=json.dumps(payload, ensure_ascii=False),
                )
            )
            updated += 1
        else:
            record.last_seen_update_id = update.id
            record.last_seen_at = utcnow()
            unchanged += 1

    existing_records = db.execute(select(MedicineRecord).where(MedicineRecord.dataset == dataset, MedicineRecord.is_active.is_(True))).scalars().all()
    removed = 0
    for record in existing_records:
        if record.source_key not in seen_keys:
            before = json.loads(record.raw_json)
            record.is_active = False
            record.last_seen_update_id = update.id
            record.last_seen_at = utcnow()
            db.add(
                MedicineChange(
                    update_id=update.id,
                    dataset=dataset,
                    source_key=record.source_key,
                    medicine_record_id=record.id,
                    change_type="removed",
                    before_json=json.dumps(before, ensure_ascii=False),
                    after_json=None,
                )
            )
            removed += 1

    db.commit()
    return {
        "added": added,
        "updated": updated,
        "removed": removed,
        "unchanged": unchanged,
        "processed": len(items),
    }


async def ingest_target_file(
    db: Session,
    gh: GitHubClient,
    update: RepoUpdate,
    path: str,
    commit_ref: str,
    owner: str,
    repo: str,
) -> dict[str, Any]:
    fetched = await gh.get_text_file(owner, repo, path, commit_ref)
    raw = fetched.text
    save_snapshot(db, update.id, path, fetched.sha, raw)
    record_artifact(
        db,
        source_name="github_repo",
        title=path,
        origin_url=fetched.html_url or fetched.download_url,
        path=path,
        content=raw.encode("utf-8"),
        content_type=fetched.content_type or "text/plain",
        parser_hint=path.split("/")[-1].replace(".json", "").replace(".html", ""),
        kind="repo_file",
        repo_update_id=update.id,
        notes=f"repo_ref={commit_ref}; repo_sha={fetched.sha}; sha256={sha256_text(raw)}",
    )

    if path == "js/latest.json":
        stats = upsert_medicines(db, update, "latest", parse_latest(raw, path))
        return {"path": path, "sha256": sha256_text(raw), **stats}
    if path == "js/vei.json":
        stats = upsert_medicines(db, update, "vei", parse_vei(raw, path))
        return {"path": path, "sha256": sha256_text(raw), **stats}
    if path == "js/pct.json":
        stats = upsert_medicines(db, update, "pct", parse_pct(raw, path))
        return {"path": path, "sha256": sha256_text(raw), **stats}
    if path == "changements.html":
        entries = [entry.__dict__ for entry in parse_changements(raw)]
        return {"path": path, "sha256": sha256_text(raw), "entries_detected": len(entries)}
    if path.endswith(".html"):
        page_summary = parse_html_page_summary(raw, path)
        return {"path": path, "sha256": sha256_text(raw), "page": page_summary.__dict__}
    return {"path": path, "sha256": sha256_text(raw), "ignored": True}


async def process_push_event(db: Session, *, owner: str, repo: str, ref: str, before_sha: str | None, after_sha: str) -> dict[str, Any]:
    gh = GitHubClient(token=settings.github_token)

    compare_url = None
    changed_files: list[str] = []

    if before_sha and set(before_sha) != {"0"}:
        compare = await gh.compare_commits(owner, repo, before_sha, after_sha)
        compare_url = compare.get("html_url")
        changed_files = [file["filename"] for file in compare.get("files", []) if is_relevant(file["filename"])]
    else:
        changed_files = sorted(PRIMARY_TARGETS)

    if not changed_files:
        changed_files = sorted(PRIMARY_TARGETS)

    update = await create_update_if_missing(
        db,
        branch=ref,
        before_sha=before_sha,
        after_sha=after_sha,
        compare_url=compare_url,
        changed_files=changed_files,
        update_kind="github",
        source_name=None,
    )

    per_file_results = []
    for path in changed_files:
        try:
            result = await ingest_target_file(db, gh, update, path, after_sha, owner, repo)
            per_file_results.append(result)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Failed to ingest %s", path)
            per_file_results.append({"path": path, "error": str(exc)})

    summary = {
        "owner": owner,
        "repo": repo,
        "ref": ref,
        "before_sha": before_sha,
        "after_sha": after_sha,
        "processed_files": per_file_results,
        "processed_at": utcnow().isoformat(),
    }
    update.summary_json = json.dumps(summary, ensure_ascii=False)
    db.commit()

    await notify_update(summary)
    return summary


async def ingest_supported_bytes_as_update(
    db: Session,
    *,
    source_name: str,
    title: str,
    filename: str,
    content: bytes,
    parser_hint: str,
    origin_url: str | None = None,
    marker: str | None = None,
    effective_date_text: str | None = None,
    monitored_source_id: int | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    parser_hint = parser_hint.lower().strip()
    if parser_hint not in SUPPORTED_MANUAL_PARSERS:
        raise ValueError(f"Unsupported parser hint: {parser_hint}")

    update_kind = "official" if monitored_source_id else "manual"
    branch_prefix = "official" if monitored_source_id else "manual"
    update = await create_synthetic_update(
        db,
        branch=f"{branch_prefix}:{source_name}",
        compare_url=origin_url,
        changed_files=[filename],
        summary={"source_name": source_name, "mode": update_kind},
        update_kind=update_kind,
        source_name=source_name,
    )
    artifact = record_artifact(
        db,
        source_name=source_name,
        title=title,
        origin_url=origin_url,
        path=filename,
        content=content,
        content_type=None,
        parser_hint=parser_hint,
        kind="official_file" if monitored_source_id else "manual_upload",
        repo_update_id=update.id,
        monitored_source_id=monitored_source_id,
        marker=marker,
        effective_date_text=effective_date_text,
        notes=notes,
        parse_status="queued",
    )

    source_path = f"{source_name}/{filename}"
    items = parse_supported_uploaded_bytes(content, filename, parser_hint, source_path)
    stats = upsert_medicines(db, update, parser_hint, items)

    artifact.parse_status = "parsed"
    artifact.notes = ((artifact.notes or "").rstrip() + f"\nnormalized_dataset={parser_hint}").strip()

    summary = {
        "source_name": source_name,
        "title": title,
        "filename": filename,
        "parser_hint": parser_hint,
        "sha256": sha256_bytes(content),
        "stats": stats,
        "marker": marker,
        "effective_date_text": effective_date_text,
        "processed_at": utcnow().isoformat(),
        "update_kind": update_kind,
    }
    update.summary_json = json.dumps(summary, ensure_ascii=False)
    db.commit()

    await notify_update(summary)
    return summary


async def mark_delivery_status(db: Session, github_delivery_id: str, status: str, error: str | None = None) -> None:
    delivery = db.execute(select(WebhookDelivery).where(WebhookDelivery.github_delivery_id == github_delivery_id)).scalar_one_or_none()
    if delivery:
        delivery.status = status
        delivery.error = error
        delivery.processed_at = utcnow()
        db.commit()
