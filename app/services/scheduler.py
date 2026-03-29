from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.db import SessionLocal
from app.services.github_client import GitHubClient
from app.services.ingestion import get_last_github_update, process_push_event
from app.services.source_monitors import check_all_sources

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None


async def run_repo_reconcile_job() -> None:
    db = SessionLocal()
    try:
        gh = GitHubClient(token=settings.github_token)
        latest_commit = await gh.get_latest_branch_commit(settings.repo_owner, settings.repo_name, settings.target_branch)
        latest_sha = latest_commit["sha"]
        last_update = get_last_github_update(db, settings.target_ref)
        before_sha = last_update.after_sha if last_update else None
        if before_sha == latest_sha:
            logger.info("Scheduler: repo already up to date at %s", latest_sha)
            return
        await process_push_event(
            db,
            owner=settings.repo_owner,
            repo=settings.repo_name,
            ref=settings.target_ref,
            before_sha=before_sha,
            after_sha=latest_sha,
        )
        logger.info("Scheduler: repo reconciliation completed to %s", latest_sha)
    except Exception:  # pragma: no cover
        logger.exception("Scheduler repo reconciliation failed")
    finally:
        db.close()


async def run_source_checks_job() -> None:
    db = SessionLocal()
    try:
        results = await check_all_sources(db)
        logger.info("Scheduler: source checks completed for %s sources", len(results))
    except Exception:  # pragma: no cover
        logger.exception("Scheduler source checks failed")
    finally:
        db.close()


def start_scheduler() -> None:
    global _scheduler
    if not settings.scheduler_enabled or _scheduler is not None:
        return

    scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone)
    scheduler.add_job(
        run_repo_reconcile_job,
        CronTrigger.from_crontab(settings.repo_reconcile_cron, timezone=settings.scheduler_timezone),
        id="repo_reconcile",
        replace_existing=True,
    )
    scheduler.add_job(
        run_source_checks_job,
        CronTrigger.from_crontab(settings.source_checks_cron, timezone=settings.scheduler_timezone),
        id="source_checks",
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("Scheduler started with timezone=%s", settings.scheduler_timezone)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
