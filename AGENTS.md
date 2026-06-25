# Project conventions

- Use uv for package management (never pip). The development dependencies from `pyproject.toml` are expected to be installed in the active environment.
- The available commands for tests, linting, formatting, and type checking should be run from the root folder:
    - tests: `pytest <relevant tests>`
    - linting: `ruff check <touched files>`
    - formatting: `ruff format <touched files>`
    - type checking: `pyright .`

## Testing and Linting

- Fix every issue reported on files you touched; don't split into "pre-existing" vs "introduced."
- Keep fixes scoped to the requested change and files touched.

## Comments and Documentation

- Documentation is in docs/content and should be updated when features are introduced or changed.
- This repo is public; use neutral language and describe *behavior*, not the bug/vulnerability being fixed.
- Stay version neutral, for example refer to "Oracle AI Database" with no version numbers (not 23ai/26ai). Exception: a feature that genuinely requires a specific minimum version may state it.

## Code style

- Ensure to follow patterns in the existing code