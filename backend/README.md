# AI Playwright Platform Backend

## Setup

```bash
cd backend
uv sync --dev
cp .env.example .env
```

## Environment

`backend/.env.example` defines the baseline application settings used by the API:

- `APP_NAME`: FastAPI application name
- `APP_ENV`: runtime environment label
- `LOG_LEVEL`: log verbosity
- `DATABASE_URL`: async SQLAlchemy connection string used by the API
- `REDIS_URL`: queue and scheduler Redis endpoint

## Run Migrations

```bash
cd backend
uv run alembic upgrade head
```

The current Alembic baseline uses `backend/alembic.ini`. Update its `sqlalchemy.url` if you want migrations to target a different database than the local default.

## Run Locally

```bash
cd backend
uv run uvicorn app.main:create_app --factory --reload
```

## Run Tests

```bash
cd backend
uv run pytest ../tests/backend -v
```

## Project Layout

- `src/app/main.py`: app factory and router registration
- `src/app/api/`: HTTP endpoints and dependency wiring
- `src/app/domains/control_plane/`: control-plane DTOs, repository, service
- `src/app/infrastructure/`: database, queue, and runtime adapters
- `alembic/`: migration environment and schema revisions

## Tests

```bash
cd backend
uv run pytest ../tests/backend/test_boot.py -v
```
