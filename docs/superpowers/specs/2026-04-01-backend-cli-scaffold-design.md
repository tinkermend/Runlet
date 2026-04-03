# Backend & CLI Scaffold Design (2026-04-01)

## Summary

This spec describes the minimal backend and CLI scaffolding required for Task 1. The backend exposes a FastAPI factory that registers a single health router, while the CLI provides a Typer-driven command surface. Configuration, documentation, and tests are laid out so future domains and runners can plug into this foundation without reworking the bootstrapping pieces.

## Architecture

- **Backend package** under `worktrees/foundation-step1-2/backend` is a Python module with its own `pyproject.toml`, README, env example, and source tree at `src/app`. It follows an app-factory pattern so `TestClient(create_app())` works for startup tests and future integration.
- **CLI package** under `worktrees/foundation-step1-2/cli` lives separately so CLI-only dependencies (Typer) stay out of the backend execution path. It exposes a `doctor` command that can be extended later.
- Runtime settings are centralized via a Pydantic `BaseSettings` subclass so we can keep env validation in one place and reference the same values from the backend and possibly CLI helpers.

## Components

1. `backend/src/app/main.py`: exposes `create_app()` which loads settings, instantiates FastAPI, and includes routers. Keeps module-level side effects minimal so the test client can boot the same app as production.
2. `backend/src/app/api/router.py`: registers `/healthz`; returns a consistent JSON payload (`{"status": "ok"}`). Can later import additional routers.
3. `backend/src/app/config/settings.py`: wraps env variables (e.g., `APP_ENV`, `LOG_LEVEL`) with defaults. Ensures the app fails fast if a required config is missing.
4. `backend/.env.example`: maps the settings for new contributors.
5. `backend/README.md`: documents how to install dependencies, run the server, and execute tests.
6. `backend/pyproject.toml`: declares backend dependencies (`fastapi`, `uvicorn`, `pydantic`, `pytest`, etc.) and `[tool.uvicorn]` metadata if needed.
7. `cli/src/openweb_cli/main.py`: defines `typer.Typer()` and the `doctor` command per the instructions, keeping the entrypoint lean and independent.

## Data Flow

1. Test or production flow:
   - Call `create_app()`.
   - FastAPI registers `router.include_router(api_router)`.
   - `/healthz` request hits the router and returns `{"status": "ok"}` with status code 200.
   - Settings instantiate once during app creation so the same values propagate to all future routers.
2. CLI flow: running `python -m openweb_cli` (once package and module are installed) starts Typer; `doctor` prints `ok`. Future commands can import backend clients as needed.

## Error Handling

- FastAPI built-in exception handlers cover route errors; the single handler returns a deterministic payload.
- `BaseSettings` raises `ValidationError` if required env vars are missing, preventing silent misconfiguration.
- CLI inherits Typer’s defaults so wrong args print help and exit cleanly.

## Testing

- `tests/backend/test_boot.py` (under the root tests directory) instantiates `TestClient(create_app())`, calls `/healthz`, and asserts a 200 response with `{"status": "ok"}`.
- Running `uv run pytest ../tests/backend/test_boot.py -v` from the backend directory covers the new route.
- No extra test frameworks are needed for this iteration.

## Rollout Steps

1. Add the backend and CLI files described above.
2. Run `uv run pytest ../tests/backend/test_boot.py -v` from `worktrees/foundation-step1-2/backend`.
3. Commit scaffold once tests pass.

## Open Questions

- Are there additional backend config keys or CLI commands expected on day one?
- Should the CLI live in the same virtual environment as the backend once packaged, or be fully independent?

## Next Steps

1. Dispatch the spec-document-reviewer subagent (per the workflow) once this doc is ready.
2. Obtain review approval and capture it here before implementation.
3. After spec review and user sign-off, invoke the writing-plans skill to produce an implementation plan aligned with this design.
