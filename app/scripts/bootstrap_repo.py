from __future__ import annotations

import asyncio

from app.config import settings
from app.db import SessionLocal
from app.services.github_client import GitHubClient
from app.services.ingestion import process_push_event
from app.services.storage import ensure_storage_dir


async def main() -> None:
    ensure_storage_dir()
    gh = GitHubClient(token=settings.github_token)
    latest = await gh.get_latest_branch_commit(settings.repo_owner, settings.repo_name, settings.target_branch)
    after_sha = latest["sha"]

    db = SessionLocal()
    try:
        summary = await process_push_event(
            db,
            owner=settings.repo_owner,
            repo=settings.repo_name,
            ref=settings.target_ref,
            before_sha=None,
            after_sha=after_sha,
        )
        print(summary)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
