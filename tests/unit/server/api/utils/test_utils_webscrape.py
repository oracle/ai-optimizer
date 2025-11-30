"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/utils/webscrape.py
Tests for web scraping and content extraction utilities.
"""

# pylint: disable=too-few-public-methods

from unittest.mock import patch, AsyncMock

import pytest
from bs4 import BeautifulSoup

from server.api.utils import webscrape
from unit.server.api.conftest import create_mock_aiohttp_session


class TestNormalizeWs:
    """Tests for the normalize_ws function."""

    def test_normalize_ws_removes_extra_spaces(self):
        """normalize_ws should collapse multiple spaces into one."""
        result = webscrape.normalize_ws("Hello    world")
        assert result == "Hello world"

    def test_normalize_ws_removes_newlines(self):
        """normalize_ws should replace newlines with spaces."""
        result = webscrape.normalize_ws("Hello\n\nworld")
        assert result == "Hello world"

    def test_normalize_ws_strips_whitespace(self):
        """normalize_ws should strip leading/trailing whitespace."""
        result = webscrape.normalize_ws("  Hello world  ")
        assert result == "Hello world"

    def test_normalize_ws_handles_tabs(self):
        """normalize_ws should handle tab characters."""
        result = webscrape.normalize_ws("Hello\t\tworld")
        assert result == "Hello world"

    def test_normalize_ws_normalizes_unicode(self):
        """normalize_ws should normalize unicode characters."""
        # NFKC normalization should convert full-width to half-width
        result = webscrape.normalize_ws("Ｈｅｌｌｏ")  # Full-width characters
        assert result == "Hello"

    def test_normalize_ws_empty_string(self):
        """normalize_ws should handle empty string."""
        result = webscrape.normalize_ws("")
        assert result == ""


class TestCleanSoup:
    """Tests for the clean_soup function."""

    def test_clean_soup_removes_script_tags(self):
        """clean_soup should remove script tags."""
        html = "<html><body><script>alert('test')</script><p>Content</p></body></html>"
        soup = BeautifulSoup(html, "html.parser")

        webscrape.clean_soup(soup)

        assert soup.find("script") is None
        assert soup.find("p") is not None

    def test_clean_soup_removes_style_tags(self):
        """clean_soup should remove style tags."""
        html = "<html><body><style>.test{}</style><p>Content</p></body></html>"
        soup = BeautifulSoup(html, "html.parser")

        webscrape.clean_soup(soup)

        assert soup.find("style") is None

    def test_clean_soup_removes_noscript_tags(self):
        """clean_soup should remove noscript tags."""
        html = "<html><body><noscript>No JS</noscript><p>Content</p></body></html>"
        soup = BeautifulSoup(html, "html.parser")

        webscrape.clean_soup(soup)

        assert soup.find("noscript") is None

    def test_clean_soup_removes_nav_elements(self):
        """clean_soup should remove navigation elements."""
        html = '<html><body><nav id="nav">Nav</nav><p>Content</p></body></html>'
        soup = BeautifulSoup(html, "html.parser")

        webscrape.clean_soup(soup)

        assert soup.find("nav") is None

    def test_clean_soup_removes_elements_by_class(self):
        """clean_soup should remove elements with bad class names."""
        html = '<html><body><div class="footer">Footer</div><p>Content</p></body></html>'
        soup = BeautifulSoup(html, "html.parser")

        webscrape.clean_soup(soup)

        assert soup.find(class_="footer") is None

    def test_clean_soup_preserves_content(self):
        """clean_soup should preserve main content."""
        html = "<html><body><article><p>Important content</p></article></body></html>"
        soup = BeautifulSoup(html, "html.parser")

        webscrape.clean_soup(soup)

        assert soup.find("p") is not None
        assert "Important content" in soup.get_text()


class TestHeadingLevel:
    """Tests for the heading_level function."""

    def test_heading_level_h1(self):
        """heading_level should return 1 for h1."""
        soup = BeautifulSoup("<h1>Title</h1>", "html.parser")
        tag = soup.find("h1")

        result = webscrape.heading_level(tag)

        assert result == 1

    def test_heading_level_h2(self):
        """heading_level should return 2 for h2."""
        soup = BeautifulSoup("<h2>Title</h2>", "html.parser")
        tag = soup.find("h2")

        result = webscrape.heading_level(tag)

        assert result == 2

    def test_heading_level_h6(self):
        """heading_level should return 6 for h6."""
        soup = BeautifulSoup("<h6>Title</h6>", "html.parser")
        tag = soup.find("h6")

        result = webscrape.heading_level(tag)

        assert result == 6


class TestGroupBySections:
    """Tests for the group_by_sections function."""

    def test_group_by_sections_extracts_sections(self):
        """group_by_sections should extract section content."""
        html = """
        <html><body>
            <section>
                <h2>Section Title</h2>
                <p>Paragraph 1</p>
                <p>Paragraph 2</p>
            </section>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")

        result = webscrape.group_by_sections(soup)

        assert len(result) == 1
        assert result[0]["title"] == "Section Title"
        assert "Paragraph 1" in result[0]["content"]

    def test_group_by_sections_handles_articles(self):
        """group_by_sections should handle article tags."""
        html = """
        <html><body>
            <article>
                <h1>Article Title</h1>
                <p>Article content</p>
            </article>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")

        result = webscrape.group_by_sections(soup)

        assert len(result) == 1
        assert result[0]["title"] == "Article Title"

    def test_group_by_sections_no_sections(self):
        """group_by_sections should return empty list when no sections."""
        html = "<html><body><p>Plain content</p></body></html>"
        soup = BeautifulSoup(html, "html.parser")

        result = webscrape.group_by_sections(soup)

        assert not result


class TestTableToMarkdown:
    """Tests for the table_to_markdown function."""

    def test_table_to_markdown_basic_table(self):
        """table_to_markdown should convert table to markdown."""
        html = """
        <table>
            <tr><th>Header 1</th><th>Header 2</th></tr>
            <tr><td>Cell 1</td><td>Cell 2</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")

        result = webscrape.table_to_markdown(table)

        assert "| Header 1 | Header 2 |" in result
        assert "| --- | --- |" in result
        assert "| Cell 1 | Cell 2 |" in result

    def test_table_to_markdown_empty_table(self):
        """table_to_markdown should handle empty table."""
        html = "<table></table>"
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")

        result = webscrape.table_to_markdown(table)

        assert result == ""


class TestGroupByHeadings:
    """Tests for the group_by_headings function."""

    def test_group_by_headings_extracts_sections(self):
        """group_by_headings should group content by heading."""
        html = """
        <html><body>
            <h2>Section 1</h2>
            <p>Content 1</p>
            <h2>Section 2</h2>
            <p>Content 2</p>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")

        result = webscrape.group_by_headings(soup)

        assert len(result) == 2
        assert result[0]["title"] == "Section 1"
        assert result[1]["title"] == "Section 2"

    def test_group_by_headings_handles_lists(self):
        """group_by_headings should include list items."""
        html = """
        <html><body>
            <h2>List Section</h2>
            <ul>
                <li>Item 1</li>
                <li>Item 2</li>
            </ul>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")

        result = webscrape.group_by_headings(soup)

        assert len(result) == 1
        assert "Item 1" in result[0]["content"]

    def test_group_by_headings_respects_hierarchy(self):
        """group_by_headings should stop at same or higher level heading."""
        html = """
        <html><body>
            <h2>Parent</h2>
            <p>Parent content</p>
            <h3>Child</h3>
            <p>Child content</p>
            <h2>Sibling</h2>
            <p>Sibling content</p>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")

        result = webscrape.group_by_headings(soup)

        # h2 sections should not include content from sibling h2
        parent_section = next(s for s in result if s["title"] == "Parent")
        assert "Sibling content" not in parent_section["content"]


class TestSectionsToMarkdown:
    """Tests for the sections_to_markdown function."""

    def test_sections_to_markdown_basic(self):
        """sections_to_markdown should convert sections to markdown."""
        sections = [
            {"title": "Section 1", "level": 1, "paragraphs": ["Para 1"]},
            {"title": "Section 2", "level": 2, "paragraphs": ["Para 2"]},
        ]

        result = webscrape.sections_to_markdown(sections)

        assert "# Section 1" in result
        assert "## Section 2" in result

    def test_sections_to_markdown_empty_list(self):
        """sections_to_markdown should handle empty list."""
        result = webscrape.sections_to_markdown([])

        assert result == ""


class TestSlugify:
    """Tests for the slugify function."""

    def test_slugify_basic(self):
        """slugify should convert text to URL-safe slug."""
        result = webscrape.slugify("Hello World")

        assert result == "hello-world"

    def test_slugify_special_characters(self):
        """slugify should remove special characters."""
        result = webscrape.slugify("Hello! World?")

        assert result == "hello-world"

    def test_slugify_max_length(self):
        """slugify should respect max length."""
        long_text = "a" * 100
        result = webscrape.slugify(long_text, max_len=10)

        assert len(result) == 10

    def test_slugify_empty_string(self):
        """slugify should return 'page' for empty result."""
        result = webscrape.slugify("!!!")

        assert result == "page"

    def test_slugify_multiple_spaces(self):
        """slugify should collapse multiple spaces/dashes."""
        result = webscrape.slugify("Hello   World")

        assert result == "hello-world"


class TestFetchAndExtractParagraphs:
    """Tests for the fetch_and_extract_paragraphs function."""

    @pytest.mark.asyncio
    @patch("aiohttp.ClientSession")
    async def test_fetch_and_extract_paragraphs_success(self, mock_session_class):
        """fetch_and_extract_paragraphs should extract paragraphs from URL."""
        html = "<html><body><p>Paragraph 1</p><p>Paragraph 2</p></body></html>"

        mock_response = AsyncMock()
        mock_response.text = AsyncMock(return_value=html)
        create_mock_aiohttp_session(mock_session_class, mock_response)

        result = await webscrape.fetch_and_extract_paragraphs("https://example.com")

        assert len(result) == 2
        assert "Paragraph 1" in result
        assert "Paragraph 2" in result


class TestFetchAndExtractSections:
    """Tests for the fetch_and_extract_sections function."""

    @pytest.mark.asyncio
    @patch("aiohttp.ClientSession")
    async def test_fetch_and_extract_sections_with_sections(self, mock_session_class):
        """fetch_and_extract_sections should extract sections from URL."""
        html = """
        <html><body>
            <section><h2>Title</h2><p>Content</p></section>
        </body></html>
        """

        mock_response = AsyncMock()
        mock_response.text = AsyncMock(return_value=html)
        create_mock_aiohttp_session(mock_session_class, mock_response)

        result = await webscrape.fetch_and_extract_sections("https://example.com")

        assert len(result) == 1
        assert result[0]["title"] == "Title"

    @pytest.mark.asyncio
    @patch("aiohttp.ClientSession")
    async def test_fetch_and_extract_sections_falls_back_to_headings(self, mock_session_class):
        """fetch_and_extract_sections should fall back to headings."""
        html = """
        <html><body>
            <h2>Heading</h2>
            <p>Content</p>
        </body></html>
        """

        mock_response = AsyncMock()
        mock_response.text = AsyncMock(return_value=html)
        create_mock_aiohttp_session(mock_session_class, mock_response)

        result = await webscrape.fetch_and_extract_sections("https://example.com")

        assert len(result) == 1
        assert result[0]["title"] == "Heading"


class TestBadChunks:
    """Tests for the BAD_CHUNKS constant."""

    def test_bad_chunks_contains_common_elements(self):
        """BAD_CHUNKS should contain common unwanted elements."""
        assert "nav" in webscrape.BAD_CHUNKS
        assert "header" in webscrape.BAD_CHUNKS
        assert "footer" in webscrape.BAD_CHUNKS
        assert "ads" in webscrape.BAD_CHUNKS
        assert "comment" in webscrape.BAD_CHUNKS

    def test_bad_chunks_is_list(self):
        """BAD_CHUNKS should be a list."""
        assert isinstance(webscrape.BAD_CHUNKS, list)
