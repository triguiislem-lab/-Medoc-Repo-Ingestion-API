# Medoc Repo + Official Source Ingestion API

A FastAPI API that tracks the public `ballouchi/medoc` repository, polls official Tunisian medicine-related sources, stores normalized updates in PostgreSQL, and stores raw artifacts either locally or in Supabase Storage.

## Production changes in this version

- GitHub reconcile now looks only at the latest **GitHub** update state, so official-source or manual uploads can no longer poison the repo SHA tracker.
- GitHub file ingestion is pinned to the exact `after_sha` commit instead of the moving branch head.
- `RepoUpdate` now stores `update_kind` and `source_name` so GitHub, official, and manual updates are distinguishable.
- Official-source parsing was hardened for circular markers, Unicode normalization, generic `Voir plus` links, and textual dates.
- Alembic migrations were added for production schema upgrades.
- Automatic `Base.metadata.create_all(...)` now runs only for local SQLite convenience, not for production databases.
- `.env` is intentionally not tracked; use `.env.example` locally and Render environment variables in production.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scriptsctivate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

## Migrations

Use Alembic for non-SQLite environments:

```bash
alembic upgrade head
```

For an existing Supabase database that was previously created only with `create_all()`, run migrations before deploying the new app version.

## Environment variables

### Core
- `APP_ENV` = `development` or `production`
- `DATABASE_URL` = SQLAlchemy URL
- `ADMIN_API_KEY` = required in production
- `GITHUB_TOKEN` = token used to read the upstream public repo
- `GITHUB_WEBHOOK_SECRET` = only needed if you later add a webhook from a repo you control

### Artifact storage

#### Local disk
```env
ARTIFACT_STORAGE_BACKEND=local
ARTIFACT_STORAGE_DIR=./data/artifacts
```

#### Supabase Storage
```env
ARTIFACT_STORAGE_BACKEND=supabase
SUPABASE_STORAGE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_STORAGE_KEY=YOUR_SECRET_OR_SERVICE_ROLE_KEY
SUPABASE_STORAGE_BUCKET=medoc-artifacts
SUPABASE_STORAGE_PATH_PREFIX=artifacts
SUPABASE_STORAGE_CREATE_BUCKET_IF_MISSING=false
SUPABASE_STORAGE_PUBLIC=false
```

## Supabase database connection recommendation

For Render, prefer the **Supabase session pooler** connection string for long-running app traffic. Example shape:

```env
DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:PASSWORD@aws-1-REGION.pooler.supabase.com:5432/postgres?sslmode=require
```

If you intentionally use the **transaction pooler** on port `6543`, this code disables prepared statements for psycopg automatically.

## Bootstrapping the current repo state

```bash
python -m app.scripts.bootstrap_repo
```

## Manual scheduled jobs

```bash
python -m app.scripts.run_job reconcile
python -m app.scripts.run_job source-checks
```

## Render deployment

1. Push this project to **your own GitHub repository**.
2. In Render, choose **New + > Blueprint**.
3. Select your GitHub repo.
4. Render reads `render.yaml` and creates the web service plus cron jobs.
5. Add the secret environment variables in Render.
6. Run `alembic upgrade head` against the target database before first production deploy of this version.

## Useful endpoints

### Public
- `GET /health`
- `GET /api/updates`
- `GET /api/updates/latest`
- `GET /api/updates/{update_id}`
- `GET /api/medicines`
- `GET /api/medicines/{medicine_id}`
- `GET /api/medicines/search?q=...`
- `GET /api/medicines/by-source?dataset=latest`

### Admin (requires `X-Admin-Api-Key`)
- `POST /api/admin/reconcile`
- `POST /api/admin/reconcile?force=true`
- `POST /api/admin/run-source-checks`
- `POST /api/admin/run-source-check/{source_name}`
- `GET /api/admin/source-status`
- `GET /api/admin/artifacts`
- `POST /api/admin/backfills/upload`
