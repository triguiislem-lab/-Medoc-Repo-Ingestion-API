from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def notify_update(summary: dict[str, Any]) -> None:
    logger.info("Update summary: %s", summary)

    if not settings.notify_webhook_url:
        return

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(settings.notify_webhook_url, json=summary)
        response.raise_for_status()
