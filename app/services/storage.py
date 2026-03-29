from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import uuid4

from supabase import Client, create_client

from app.config import settings

ARTIFACT_ROOT = Path(settings.artifact_storage_dir)
_SUPABASE_CLIENT: Client | None = None
_BUCKET_VERIFIED = False


def ensure_storage_dir() -> Path | None:
    if settings.artifact_storage_backend == "supabase":
        _ensure_supabase_bucket()
        return None

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    return ARTIFACT_ROOT


def _get_supabase_client() -> Client:
    global _SUPABASE_CLIENT
    if _SUPABASE_CLIENT is None:
        if not settings.supabase_storage_url or not settings.supabase_storage_key:
            raise RuntimeError("Supabase storage is enabled but SUPABASE_STORAGE_URL or SUPABASE_STORAGE_KEY is missing")
        _SUPABASE_CLIENT = create_client(settings.supabase_storage_url, settings.supabase_storage_key)
    return _SUPABASE_CLIENT


def _ensure_supabase_bucket() -> None:
    global _BUCKET_VERIFIED
    if _BUCKET_VERIFIED:
        return

    bucket = settings.supabase_storage_bucket
    if not bucket:
        raise RuntimeError("Supabase storage is enabled but SUPABASE_STORAGE_BUCKET is missing")

    client = _get_supabase_client()
    try:
        client.storage.get_bucket(bucket)
    except Exception:
        if not settings.supabase_storage_create_bucket_if_missing:
            raise
        client.storage.create_bucket(bucket, {"public": settings.supabase_storage_public})
    _BUCKET_VERIFIED = True


def _build_storage_object_path(source_name: str, filename: str) -> str:
    safe_source = source_name.replace("/", "_").replace(":", "_")
    suffix = Path(filename).suffix if filename else ""
    stem = Path(filename).stem if filename else "artifact"
    safe_stem = stem.replace("/", "_").replace(":", "_")[:80] or "artifact"
    prefix = settings.supabase_storage_path_prefix.strip("/")
    pieces = [piece for piece in [prefix, safe_source, f"{safe_stem}-{uuid4().hex}{suffix}"] if piece]
    return "/".join(pieces)


def store_artifact_bytes(source_name: str, filename: str, content: bytes, content_type: str | None = None) -> str:
    if settings.artifact_storage_backend == "supabase":
        _ensure_supabase_bucket()
        client = _get_supabase_client()
        bucket = settings.supabase_storage_bucket
        if not bucket:
            raise RuntimeError("Supabase storage bucket is not configured")

        object_path = _build_storage_object_path(source_name, filename)
        file_options = {"upsert": "false"}
        if content_type:
            file_options["content-type"] = content_type
        try:
            client.storage.from_(bucket).upload(
                path=object_path,
                file=content,
                file_options=file_options,
            )
        except TypeError:
            # Some supabase-py / storage client versions don't accept BytesIO-like
            # objects for `upload`, but do accept a real filesystem path.
            suffix = Path(filename).suffix if filename else ""
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(content)
                    tmp.flush()
                    tmp_path = tmp.name
                client.storage.from_(bucket).upload(
                    path=object_path,
                    file=tmp_path,
                    file_options=file_options,
                )
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        return f"supabase://{bucket}/{object_path}"

    root = ensure_storage_dir()
    assert root is not None
    safe_source = source_name.replace("/", "_").replace(":", "_")
    subdir = root / safe_source
    subdir.mkdir(parents=True, exist_ok=True)

    suffix = Path(filename).suffix if filename else ""
    stem = Path(filename).stem if filename else "artifact"
    safe_stem = stem.replace("/", "_").replace(":", "_")[:80] or "artifact"
    path = subdir / f"{safe_stem}-{uuid4().hex}{suffix}"
    path.write_bytes(content)
    return str(path)
