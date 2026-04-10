"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.mcp.prompts.defaults.
"""
# spell-checker: disable

from server.app.mcp.prompts import defaults


def test_clean_trims_leading_blank_and_whitespace():
    """_clean removes leading blank and indentation."""
    raw = "\n    line one\n      line two\n"
    result = defaults._clean(raw)
    assert result == "line one\nline two"


def test_clean_preserves_without_blank():
    """_clean leaves untouched text unchanged."""
    raw = "already clean\nnext line"
    result = defaults._clean(raw)
    assert result == raw


def test_factory_prompts_are_cleaned():
    """Factory prompts shipped without leading spaces."""
    for item in defaults.FACTORY_PROMPTS:
        text = item["text"]
        # Ensure no leading spaces on any line and no leading blank line.
        lines = text.splitlines()
        if lines:
            assert lines[0] == lines[0].lstrip()
        for line in lines:
            assert line == line.lstrip()
