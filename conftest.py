"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Root test configuration: make anyio the single async-test backend.

``anyio_mode = "auto"`` (see ``pyproject.toml``) makes anyio claim every coroutine
test function and its async fixtures at collection time — no per-test
``@pytest.mark.anyio`` needed. ``pytest-asyncio`` stays installed but pinned to
``asyncio_mode = "strict"``, so it only ever acts on the (unused)
``@pytest.mark.asyncio`` marker and never auto-claims async tests/fixtures.

Why a single owner matters: with both plugins auto-claiming, an async fixture and the
test body that consumes it can be set up on two different event loops, which surfaces
as ``RuntimeError: ... got Future ... attached to a different loop`` for any fixture
that binds to its creating loop (e.g. an oracledb async pool). Whether the two plugins
happen to share a loop is platform/version dependent (they do on macOS, they do not on
the Linux CI runners), so routing every async test through anyio is the robust fix.

Note: anyio only attaches ``anyio_backend`` to *coroutine* tests, so a *sync* test that
depends on an async fixture is not handled by anyio (nor, in strict mode, by
pytest-asyncio). Such tests must be written as ``async def``.
"""

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run all anyio tests on the asyncio backend (no trio dependency).

    Overrides anyio's default ``anyio_backend`` (which would also parametrize over
    trio) for every test tree.
    """
    return "asyncio"
