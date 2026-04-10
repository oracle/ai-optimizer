"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for embed web scrape utilities.
"""
# spell-checker: disable

import pytest
from bs4 import BeautifulSoup

from server.app.embed.webscrape import (
    group_by_headings,
    group_by_sections,
    normalize_ws,
    slugify,
)

# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_slugify_basic():
    """Converts text to URL-safe slug."""
    assert slugify("Hello World") == "hello-world"


@pytest.mark.unit
def test_slugify_special_chars():
    """Removes special characters."""
    assert slugify("foo@bar.com/page") == "foobarcompage"


@pytest.mark.unit
def test_slugify_empty():
    """Returns 'page' for empty input."""
    assert slugify("") == "page"


@pytest.mark.unit
def test_slugify_max_len():
    """Truncates to max_len."""
    result = slugify("a" * 100, max_len=10)
    assert len(result) == 10


# ---------------------------------------------------------------------------
# normalize_ws
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_normalize_ws():
    """Collapses multiple whitespace into single space."""
    assert normalize_ws("  hello   world  ") == "hello world"
    assert normalize_ws("tab\there") == "tab here"


# ---------------------------------------------------------------------------
# group_by_sections
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_group_by_sections():
    """Extracts sections from HTML."""
    html = """
    <html>
    <body>
        <section>
            <h2>Section 1</h2>
            <p>Content 1</p>
        </section>
        <section>
            <h2>Section 2</h2>
            <p>Content 2</p>
            <p>More content</p>
        </section>
    </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    sections = group_by_sections(soup)
    assert len(sections) == 2
    assert sections[0]["title"] == "Section 1"
    assert sections[0]["content"] == "Content 1"
    assert "More content" in sections[1]["content"]


@pytest.mark.unit
def test_group_by_sections_no_heading():
    """Section without heading gets empty title."""
    html = "<html><body><section><p>Content only</p></section></body></html>"
    soup = BeautifulSoup(html, "lxml")
    sections = group_by_sections(soup)
    assert len(sections) == 1
    assert sections[0]["title"] == ""


# ---------------------------------------------------------------------------
# group_by_headings
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_group_by_headings():
    """Groups content under heading hierarchy."""
    html = """
    <html>
    <body>
        <h1>Main Title</h1>
        <p>Intro paragraph</p>
        <h2>Sub Section</h2>
        <p>Sub content</p>
    </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    groups = group_by_headings(soup)
    assert len(groups) == 2
    assert groups[0]["title"] == "Main Title"
    assert "Intro paragraph" in groups[0]["content"]
    assert groups[1]["title"] == "Sub Section"


@pytest.mark.unit
def test_group_by_headings_with_lists():
    """Includes list items in heading groups."""
    html = """
    <html>
    <body>
        <h2>Features</h2>
        <ul>
            <li>Fast</li>
            <li>Reliable</li>
        </ul>
    </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    groups = group_by_headings(soup)
    assert len(groups) == 1
    assert "Fast" in groups[0]["content"]
    assert "Reliable" in groups[0]["content"]
