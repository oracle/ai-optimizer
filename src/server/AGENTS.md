# Repository Guidelines

## Project Structure & Module Organization
- `app/` hosts FastAPI source; key modules include `api/` (routers), `core/` (settings, logging), and `db/` (Oracle connectivity). The entrypoint lives in `app/main.py`.
- `tests/` mirrors the runtime layout (`tests/api`, `tests/core`, `tests/db`) and contains unit coverage for each layer.
- `scripts/entrypoint.sh` wraps container startup, while `tns_admin/` stores wallet artifacts required for Oracle connectivity.

## Build, Test, and Development Commands
- `python3.11 -m venv .venv --copies && source .venv/bin/activate` creates an isolated environment matching the project baseline.
- `uv pip install -e ".[all-test]"` installs the server with testing extras; rerun after dependency changes.
- `uvicorn server.app.main:app --reload --port 8000` starts the API locally with hot reload.
- `pytest tests -v` executes the full test suite; pair it with `--cov=app` to monitor coverage.
- `pylint app tests` enforces linting via the bundled `.pylintrc` ruleset.

## Coding Style & Naming Conventions
- Follow PEP 8 with four-space indentation and prefer single quotes for strings.
- Use descriptive module aliases (e.g., `from server.app import main as app_main`) and type hints for public functions.
- Place FastAPI routers in `app/api/v1/endpoints/` with filenames matching the resource, and keep business logic inside `app/api` utilities or service modules.

## Testing Guidelines
- Add new tests beside the feature under `tests/<layer>/`; name files `test_<feature>.py` and functions `test_<behavior>`. 
- Use `pytest` fixtures from `tests/conftest.py` to stub settings and database access instead of ad-hoc mocks.
- Ensure new routes include success and failure scenarios, and update coverage-critical modules before requesting review.

## Commit & Pull Request Guidelines
- Sign every commit with `git commit --signoff` to comply with the Oracle Contributor Agreement.
- Write present-tense, scope-focused commit messages (`fix: validate probes auth`) and reference GitHub issues in the body.
- Pull requests must describe the change, list validation commands (tests, lint), and attach log snippets or screenshots when modifying API surface or deployment scripts.

## Security & Configuration Tips
- Never commit secrets; keep wallets inside `tns_admin/` and ignore environment files.
- Set `AIO_API_KEY`, `AIO_DB_*`, and optional `AIO_SERVER_URL_PREFIX` via environment variables when running locally.
- Validate configuration changes against the documented Oracle AI Optimizer security posture before merging.
