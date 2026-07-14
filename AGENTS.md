# Project conventions

- Use uv for package management (never pip). The development dependencies from `pyproject.toml` are expected to be installed in the active environment.
- The available commands for tests, linting, formatting, and type checking should be run from the root folder:
    - tests: `pytest <relevant tests>`
    - linting: `ruff check <touched files>`
    - formatting: `ruff format <touched files>`
    - type checking: `pyright .`

## Testing and Linting

- Never run the project's full test suite.  If additional confidence would normally come from a full suite run, recommend that the user perform it after reviewing the changes.
- Fix every issue reported on files you touched; don't split into "pre-existing" vs "introduced."
- Keep fixes scoped to the requested change and files touched.
- A real Oracle database is available for integration testing. Integration tests should use it to verify behavior whenever practical, rather than relying solely on mocks or in-memory databases.
- Async tests use AnyIO (`anyio_mode = "auto"`), while `pytest-asyncio` remains in `strict` mode. Never introduce a second async event-loop owner (for example, `asyncio_mode = "auto"`, `@pytest.mark.asyncio`, or an AnyIO async-marking hook). Never let a synchronous test depend on an async fixture; make such tests `async def` instead.

## Comments and Documentation

- Documentation is in docs/content and should be updated when features are introduced or changed.
- Ground documentation and operational guidance in the repository's current implementation. Before describing installation, runtime, environment, container, or subprocess behavior, inspect the relevant source, Dockerfiles, entrypoints, and configuration. Use external documentation only to verify facts about external tools.
- This repo is public; use neutral language and describe *behavior*, not the bug/vulnerability being fixed.
- Stay version neutral, for example refer to "Oracle AI Database" with no version numbers (not 23ai/26ai). Exception: a feature that genuinely requires a specific minimum version may state it.
- Do not run pytest when only documentation changes.

## Code style

- Ensure to follow patterns in the existing code
