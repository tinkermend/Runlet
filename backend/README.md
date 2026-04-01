# AI Playwright Platform Backend

## Setup

```bash
cd backend
uv sync
```

## Run Locally

```bash
cd backend
uv run uvicorn app.main:create_app --factory --reload
```

## Tests

```bash
cd backend
uv run pytest ../tests/backend/test_boot.py -v
```
