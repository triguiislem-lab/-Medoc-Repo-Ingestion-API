from __future__ import annotations

import asyncio
import sys

from app.services.scheduler import run_repo_reconcile_job, run_source_checks_job
from app.services.storage import ensure_storage_dir


async def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"reconcile", "source-checks"}:
        raise SystemExit("Usage: python -m app.scripts.run_job [reconcile|source-checks]")

    ensure_storage_dir()

    if sys.argv[1] == "reconcile":
        await run_repo_reconcile_job()
        return

    if sys.argv[1] == "source-checks":
        await run_source_checks_job()
        return


if __name__ == "__main__":
    asyncio.run(main())
