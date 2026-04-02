from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.medicines import router as medicines_router
from app.api.updates import router as updates_router
from app.api.webhook_github import router as webhook_router
from app.config import settings
from app.db import Base, engine
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.storage import ensure_storage_dir

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
    ensure_storage_dir()
    start_scheduler()
    logger.info("Application startup completed")
    try:
        yield
    finally:
        stop_scheduler()
        logger.info("Application shutdown completed")


app = FastAPI(title=settings.app_name, version="0.4.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        # add your frontend production URL here
        # "https://your-frontend-domain.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.app_env,
        "scheduler_enabled": settings.scheduler_enabled,
        "artifact_storage_backend": settings.artifact_storage_backend,
    }


app.include_router(webhook_router, prefix=settings.api_prefix)
app.include_router(updates_router, prefix=settings.api_prefix)
app.include_router(medicines_router, prefix=settings.api_prefix)
app.include_router(admin_router, prefix=settings.api_prefix)
