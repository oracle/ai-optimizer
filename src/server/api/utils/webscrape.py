from bs4 import BeautifulSoup, Comment
import re, unicodedata
from typing import List, Dict, Tuple
import aiohttp

BAD_CHUNKS = [
    "nav","header","footer","aside","form","menu","breadcrumb","toc","pagination",
    "subscribe","advert","ads","promo","social","share","comment","related","widget",
    "modal","banner","cookie","newsletter","disclaimer"
]

def normalize_ws(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def clean_soup(soup: BeautifulSoup) -> None:
    for el in soup(["script","style","noscript","template","svg","canvas","iframe"]):
        el.decompose()
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    for tag in soup.find_all(True):
        ident = " ".join([
            (tag.get("id") or ""),
            " ".join(tag.get("class") or []),
            (tag.get("role") or "")
        ]).lower()
        if any(b in ident for b in BAD_CHUNKS):
            tag.decompose()

def heading_level(tag) -> int:
    return int(tag.name[1])

def group_by_sections(soup):
    sections = []
    for section in soup.find_all(['section', 'article']):
        # Use the first heading if present for section title
        heading = section.find(re.compile('^h[1-6]$'))
        title = normalize_ws(heading.get_text()) if heading else ""
        paragraphs = []
        for p in section.find_all('p'):
            txt = normalize_ws(p.get_text())
            if txt:
                paragraphs.append(txt)
        if paragraphs:
            # All paragraphs in the section are joined with blanklines; change as you prefer
            sections.append({"title": title, "content": "\n\n".join(paragraphs)})
    return sections

def table_to_markdown(table):
    # Simple HTML table to Markdown converter
    rows = []
    for tr in table.find_all("tr"):
        cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        rows.append(cols)
    # Make Markdown
    md = ""
    if rows:
        md += "| " + " | ".join(rows[0]) + " |\n"
        md += "| " + " | ".join("---" for _ in rows[0]) + " |\n"
        for row in rows[1:]:
            md += "| " + " | ".join(row) + " |\n"
    return md

def group_by_headings(soup):
    grouped = []
    # Find all headings
    for hdr in soup.find_all(re.compile("^h[1-6]$")):
        title = normalize_ws(hdr.get_text())
        buffer = []
        # Find next siblings until another heading of this or higher level
        for sib in hdr.find_next_siblings():
            if sib.name and re.match(r"^h[1-6]$", sib.name, re.I):
                if int(sib.name[1]) <= int(hdr.name[1]):
                    break
            if sib.name == "p":
                text = normalize_ws(sib.get_text())
                if text:
                    buffer.append(text)
            elif sib.name in ("ul", "ol"):
                for li in sib.find_all('li'):
                    text = normalize_ws(li.get_text())
                    if text:
                        buffer.append("• " + text)
        if buffer:
            grouped.append({"title": title, "content": "\n\n".join(buffer)})
    return grouped

def sections_to_markdown(sections: List[Dict]) -> str:
    lines: List[str] = []
    for s in sections:
        hashes = "#" * max(1, min(6, s["level"]))
        lines.append(f"{hashes} {s['title']}")
        for p in s["paragraphs"]:
            lines.append(p)
            lines.append("")
    out = "\n".join(lines).strip()
    return out + "\n" if out else out

def slugify(text: str, max_len: int = 80) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:max_len] or "page"
    
async def fetch_and_extract_paragraphs(url):
    paragraphs = []
    async with aiohttp.ClientSession() as session:
        async with session.get(str(url)) as response:
            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            
            for script in soup(["script", "style"]):
                script.decompose()
            for element in soup(text=lambda text: isinstance(text, Comment)):
                element.extract()
            
            for p in soup.find_all("p"):
                txt = normalize_ws(p.get_text())
                if txt:  
                    paragraphs.append(txt)
    return paragraphs

async def fetch_and_extract_sections(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(str(url)) as response:
            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            
            for script in soup(["script", "style"]):
                script.decompose()
            for element in soup(text=lambda text: isinstance(text, Comment)):
                element.extract()
            
            # Prefer by section, or fallback to headings
            chunks = group_by_sections(soup)
            if not chunks:
                chunks = group_by_headings(soup)
    return chunks