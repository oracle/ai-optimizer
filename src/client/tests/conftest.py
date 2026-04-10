"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared test fixtures for client unit tests.
"""
# spell-checker: disable

import json
from unittest.mock import MagicMock

import httpx
import pytest

# ---------------------------------------------------------------------------
# Streamlit session_state stand-in
# ---------------------------------------------------------------------------


class AttrDict(dict):
    """Dict that also supports attribute access, like Streamlit session_state."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        try:
            del self[name]
        except KeyError:
            raise AttributeError(name) from None


@pytest.fixture
def make_state():
    """Factory fixture: build an AttrDict mimicking Streamlit session_state."""

    def _make(aliases=None, current_alias=None, extra=None):
        db_configs = [{"alias": a} for a in (aliases or [])]
        data = AttrDict(
            {
                "settings": {
                    "database_configs": db_configs,
                    "client_settings": {
                        "database": {"alias": current_alias} if current_alias else {},
                    },
                },
            }
        )
        if extra:
            data.update(extra)
        return data

    return _make


@pytest.fixture
def mock_st():
    """Return a MagicMock for the ``st`` module with context-manager widgets."""
    m = MagicMock()
    for attr in ("form", "spinner", "popover"):
        ctx = getattr(m, attr).return_value
        ctx.__enter__ = MagicMock()
        ctx.__exit__ = MagicMock(return_value=False)

    # st.columns() must return a list whose length matches the input widths
    # so that tuple-unpacking (e.g. col_a, col_b, _ = st.columns([...]))
    # works correctly in the code under test.
    def _make_cols(widths, **_kw):
        n = widths if isinstance(widths, int) else len(widths)
        return [MagicMock() for _ in range(n)]

    m.columns.side_effect = _make_cols

    # Sidebar context managers and columns
    m.sidebar.columns.side_effect = _make_cols
    for attr in ("container", "expander"):
        ctx = getattr(m.sidebar, attr).return_value
        ctx.__enter__ = MagicMock()
        ctx.__exit__ = MagicMock(return_value=False)
    # Sidebar container with border support
    m.sidebar.container.side_effect = None
    sb_container_ctx = m.sidebar.container.return_value
    sb_container_ctx.__enter__ = MagicMock()
    sb_container_ctx.__exit__ = MagicMock(return_value=False)

    # st.container() context manager
    container_ctx = m.container.return_value
    container_ctx.__enter__ = MagicMock()
    container_ctx.__exit__ = MagicMock(return_value=False)

    # st.expander() context manager
    expander_ctx = m.expander.return_value
    expander_ctx.__enter__ = MagicMock()
    expander_ctx.__exit__ = MagicMock(return_value=False)

    # st.empty() returns a mock with standard methods
    m.empty.return_value = MagicMock()

    return m


class Rerun(Exception):
    """Sentinel raised by mock st.rerun to stop execution cleanly."""


# ---------------------------------------------------------------------------
# Shared test helpers (imported directly, not fixtures)
# ---------------------------------------------------------------------------


def make_http_error(status_code=400, detail="error"):
    """Build an ``httpx.HTTPStatusError`` with a JSON detail body."""
    body = json.dumps({"detail": detail}).encode()
    resp = httpx.Response(
        status_code=status_code,
        request=httpx.Request("GET", "http://test"),
        content=body,
        headers={"content-type": "application/json"},
    )
    return httpx.HTTPStatusError("error", request=resp.request, response=resp)


def make_mock_tabs(count):
    """Create *count* MagicMock tab context managers for ``st.tabs()``."""
    tabs = [MagicMock() for _ in range(count)]
    for t in tabs:
        t.__enter__ = MagicMock()
        t.__exit__ = MagicMock(return_value=False)
    return tabs


def base_test_settings(**overrides):
    """Base ``settings`` dict for test state construction.

    Provides empty defaults for common keys; callers add or override as needed.
    """
    defaults = {
        "database_configs": [],
        "model_configs": [],
        "client_settings": {},
    }
    defaults.update(overrides)
    return defaults
