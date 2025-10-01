from bs4 import BeautifulSoup, Comment
import re, unicodedata
from readability import Document
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

def extract_sections_from_html(html: str, default_title: str | None = None) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    clean_soup(soup)
    body = soup.body or soup

    headings = body.find_all(re.compile(r"^h[1-6]$", re.I))
    sections: List[Dict] = []

    if not headings:
        paras = [
            normalize_ws(t.get_text(" ", strip=True))
            for t in body.find_all(["p","li"])
            if t.get_text(strip=True)
        ]
        if paras:
            title = default_title or (soup.title.string.strip() if soup.title and soup.title.string else "Document")
            sections.append({"title": title, "level": 1, "paragraphs": paras})
        return sections

    for h in headings:
        level = heading_level(h)
        title = normalize_ws(h.get_text(" ", strip=True))
        paras: List[str] = []

        for sib in h.next_siblings:
            if getattr(sib, "name", None) and re.match(r"^h[1-6]$", sib.name, re.I):
                if int(sib.name[1]) <= level:
                    break

            if getattr(sib, "name", None) in ("p","li"):
                txt = normalize_ws(sib.get_text(" ", strip=True))
                if txt:
                    paras.append(txt)
            elif getattr(sib, "name", None) in ("ul","ol"):
                for li in sib.find_all("li"):
                    txt = normalize_ws(li.get_text(" ", strip=True))
                    if txt:
                        paras.append(f"- {txt}")
            elif getattr(sib, "name", None) in ("div","section","article"):
                for p in sib.find_all(["p","li"], recursive=True):
                    txt = normalize_ws(p.get_text(" ", strip=True))
                    if txt:
                        paras.append(txt)

        if paras:
            sections.append({"title": title, "level": level, "paragraphs": paras})

    return sections

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

def extract_main_html(html: str) -> Tuple[str, str | None]:
    try:
        doc = Document(html)
        return doc.summary(html_partial=True), doc.short_title()
    except Exception:
        return html, None
    
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