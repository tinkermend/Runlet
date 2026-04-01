# AI Playwright Platform Backend

## Setup

```bash
cd backend
uv sync
```

## Run Locally

```bash
cd backend
PYTHONPATH=src uv run uvicorn app.main:create_app --factory --reload
```

## Tests

```bash
cd backend
PYTHONPATH=src uv run pytest ../tests/backend/test_boot.py -v
```
