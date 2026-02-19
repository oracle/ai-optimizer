# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Install

```bash
python3.11 -m venv .venv --copies && source .venv/bin/activate
pip3.11 install --upgrade pip wheel setuptools uv
uv pip install -e ".[all-test]"   # server + client + test deps
```

## Running the Application

```bash
cd src/
uvicorn server.app.main:app --reload --port 8000        # server only
streamlit run client/app/main.py --server.port 8501      # client (auto-starts server if unreachable)
```

## Testing

**All test commands must be run from `src/`.**

```bash
cd src/
pytest server/tests -v                              # full suite
pytest server/tests -v -m "unit"                    # unit tests only (mocked, fast)
pytest server/tests -v -m "not db"                  # skip tests requiring Oracle container
pytest server/tests/api/test_settings.py -v         # single file
pytest server/tests -v --cov=app                    # with coverage
```

**Markers:** `unit`, `integration`, `slow`, `db` (requires Docker Oracle container), `db_container` (alias for `db`).

**Async tests must use `@pytest.mark.anyio`** (not `@pytest.mark.asyncio`). FastAPI runs on AnyIO; mixing pytest-asyncio causes conflicts.

Test config is in `pytest.ini` with `pythonpath = src tests` and `--import-mode=importlib`.

## Linting

```bash
cd src/
pylint app tests                        # lint server code and tests
```

Pylint config: `src/.pylintrc`. Max line length 120. `fail-under=10`. Python 3.11 target.

## Architecture

**FastAPI server** (`src/server/app/`) + **Streamlit client** (`src/client/app/`), communicating over HTTP with `X-API-Key` header auth (HMAC comparison in `server/app/api/deps.py`).

### Server (`src/server/app/`)

- **Entrypoint:** `main.py` — creates the FastAPI app with a lifespan that initializes DB schema, loads persisted database configs, loads OCI profiles, then persists settings.
- **API layer:** `api/v1/endpoints/` has route handlers; `api/v1/schemas/` has Pydantic response models; `api/v1/router.py` aggregates routes under `/v1` prefix. Unauthenticated: `/v1/liveness`, `/v1/readiness`. Everything else requires `X-API-Key`.
- **Database layer:** `database/` — in-memory registry (`_DATABASE_REGISTRY` dict) of `DatabaseState` objects, each wrapping `oracledb.AsyncConnectionPool`. Settings persisted to `aio_settings` table in Oracle DB. `database/__init__.py` has the core lifecycle functions.
- **OCI integration:** `oci/` — profile registry for Oracle Cloud auth configs, parsed from `~/.oci/config`, persisted alongside database settings.
- **Config:** `core/config.py` — Pydantic `BaseSettings` with `AIO_` env prefix, loads from `.env.{AIO_ENV}` (defaults to `.env.dev`). Auto-generates `AIO_API_KEY` if unset.

### Client (`src/client/app/`)

- **Entrypoint:** `main.py` — Streamlit app that fetches server settings on load. Auto-spawns the server subprocess if unreachable.
- **Server communication:** `core/api.py` — httpx-based client calling `/v1/settings`, `/v1/oci`, `/v1/db`.
- **Content pages:** `content/` directory for Streamlit page modules.

### Shared

- `src/logging_config.py` — centralized logging setup (don't introduce separate logging).
- `src/_version.py` — resolves version from `importlib.metadata`, fallback `"0.0.0"`.

## Key Patterns

- **Environment variables** all prefixed `AIO_` (e.g., `AIO_DB_USERNAME`, `AIO_SERVER_PORT`, `AIO_API_KEY`).
- **Registry pattern** for databases and OCI profiles: in-memory dicts with persistence to Oracle `aio_settings` table as JSON.
- **Async-first:** server uses `oracledb.AsyncConnectionPool` and async FastAPI handlers throughout.
- **Test fixtures** in `server/tests/conftest.py`: `oracle_db_container` (session-scoped Docker container), `oracle_connection`, `configure_db_env`, `app_client`.

## Style

- PEP 8, 4-space indentation, single quotes for strings.
- Place routers in `app/api/v1/endpoints/` with filenames matching the resource.
- Sign every commit with `git commit --signoff` (Oracle Contributor Agreement).
