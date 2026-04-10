"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Web scraping utilities for extracting structured content from HTML pages.
"""
# spell-checker:ignore slugified

import re
import unicodedata

import httpx
from bs4 import BeautifulSoup, Comment

BAD_CHUNKS = [
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "menu",
    "breadcrumb",
    "toc",
    "pagination",
    "subscribe",
    "advert",
    "ads",
    "promo",
    "social",
    "share",
    "comment",
    "related",
    "widget",
    "modal",
    "banner",
    "cookie",
    "newsletter",
    "disclaimer",
]


def normalize_ws(s: str) -> str:
    """Normalize whitespace in a string."""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def clean_soup(soup: BeautifulSoup) -> None:
    """Remove unwanted elements from BeautifulSoup object."""
    for el in soup(["script", "style", "noscript", "template", "svg", "canvas", "iframe"]):
        el.decompose()
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    for tag in soup.find_all(True):
        ident = " ".join(
            [str(tag.get("id") or ""), " ".join(str(c) for c in (tag.get("class") or [])), str(tag.get("role") or "")]
        ).lower()
        if any(b in ident for b in BAD_CHUNKS):
            tag.decompose()


def group_by_sections(soup: BeautifulSoup) -> list[dict]:
    """Group content by section and article tags."""
    sections = []
    for section in soup.find_all(["section", "article"]):
        heading = section.find(re.compile("^h[1-6]$"))
        title = normalize_ws(heading.get_text()) if heading else ""
        paragraphs = []
        for p in section.find_all("p"):
            txt = normalize_ws(p.get_text())
            if txt:
                paragraphs.append(txt)
        if paragraphs:
            sections.append({"title": title, "content": "\n\n".join(paragraphs)})
    return sections


def group_by_headings(soup: BeautifulSoup) -> list[dict]:
    """Group content by heading hierarchy."""
    grouped = []
    for hdr in soup.find_all(re.compile("^h[1-6]$")):
        title = normalize_ws(hdr.get_text())
        buffer = []
        for sib in hdr.find_next_siblings():
            if sib.name and re.match(r"^h[1-6]$", sib.name, re.I):
                if int(sib.name[1]) <= int(hdr.name[1]):
                    break
            if sib.name == "p":
                text = normalize_ws(sib.get_text())
                if text:
                    buffer.append(text)
            elif sib.name in ("ul", "ol"):
                for li in sib.find_all("li"):
                    text = normalize_ws(li.get_text())
                    if text:
                        buffer.append("• " + text)
        if buffer:
            grouped.append({"title": title, "content": "\n\n".join(buffer)})
    return grouped


def slugify(text: str, max_len: int = 80) -> str:
    """Convert text to URL-safe slug."""
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:max_len] or "page"


async def fetch_and_extract_sections(url: str) -> list[dict]:
    """Fetch URL and extract sections by structure.

    Uses httpx (async) instead of aiohttp for consistency with the rest
    of the codebase.
    """
    async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
        response = await client.get(str(url))
        response.raise_for_status()
        html = response.text

    soup = BeautifulSoup(html, "lxml")
    clean_soup(soup)

    chunks = group_by_sections(soup)
    if not chunks:
        chunks = group_by_headings(soup)
    return chunks
