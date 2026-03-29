from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Medoc Repo Ingestion API"
    app_env: str = "development"
    database_url: str = "sqlite:///./medoc.db"
    api_prefix: str = "/api"
    github_webhook_secret: str = "change-me"
    github_token: str | None = None
    repo_owner: str = "ballouchi"
    repo_name: str = "medoc"
    target_branch: str = "gh-pages"
    target_ref: str = "refs/heads/gh-pages"
    notify_webhook_url: str | None = None
    admin_api_key: str | None = None
    log_level: str = "INFO"

    # Scheduler / source monitor settings
    scheduler_enabled: bool = True
    scheduler_timezone: str = "Africa/Tunis"
    repo_reconcile_cron: str = "15 6 * * *"
    source_checks_cron: str = "45 6 * * *"

    # Polite fetching / artifact storage
    http_user_agent: str = "medoc-fastapi-api/0.3 (+contact:triguiislem1@gmail.com)"
    artifact_storage_backend: str = "local"  # local | supabase
    artifact_storage_dir: str = "./data/artifacts"
    supabase_storage_url: str | None = None
    supabase_storage_key: str | None = None
    supabase_storage_bucket: str | None = None
    supabase_storage_path_prefix: str = "artifacts"
    supabase_storage_create_bucket_if_missing: bool = False
    supabase_storage_public: bool = False
    auto_download_official_files: bool = True
    auto_ingest_supported_official_files: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        backend = self.artifact_storage_backend.strip().lower()
        self.artifact_storage_backend = backend
        if backend not in {"local", "supabase"}:
            raise ValueError("ARTIFACT_STORAGE_BACKEND must be either 'local' or 'supabase'")

        if backend == "supabase":
            missing = [
                name
                for name, value in {
                    "SUPABASE_STORAGE_URL": self.supabase_storage_url,
                    "SUPABASE_STORAGE_KEY": self.supabase_storage_key,
                    "SUPABASE_STORAGE_BUCKET": self.supabase_storage_bucket,
                }.items()
                if not value
            ]
            if missing:
                raise ValueError(
                    "Supabase artifact storage is enabled but these settings are missing: " + ", ".join(missing)
                )

        if self.is_production and not self.admin_api_key:
            raise ValueError("ADMIN_API_KEY must be set when APP_ENV=production")

        return self


settings = Settings()
