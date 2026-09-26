"""Download the pinned corpus into ``data/raw`` and write its manifest.

Three sources, one per input format:

* **fastapi** (Markdown): the tutorial from a tagged release of the FastAPI repo.
* **pydocs** (HTML): Python standard-library reference pages.
* **arxiv** (PDF): versioned retrieval/RAG papers.

Each source is normalized to what a reader of the rendered site would see.
That is the only preprocessing done here; everything else is left to the
parser so the chunk inspector can show it.
"""

import hashlib
import io
import logging
import re
import tarfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from html import escape
from pathlib import Path, PurePosixPath

import httpx
from bs4 import BeautifulSoup

from lemma_rag.ingest.config import ArxivSource, CorpusConfig, FastApiSource, PyDocsSource
from lemma_rag.ingest.models import ManifestEntry, SourceFormat
from lemma_rag.ingest.pipeline import MANIFEST_NAME, write_jsonl

log = logging.getLogger(__name__)

# arXiv asks automated clients for no more than one request every 3 seconds.
ARXIV_DELAY_S = 3.0
# arXiv throttles with 429/503 under load.
_RETRY_STATUSES = frozenset({429, 500, 502, 503})
_ARXIV_ATTEMPTS = 4

# `{* ../../docs_src/query_params/tutorial001_py310.py hl[9] *}`: an mkdocs
# macro that the FastAPI site replaces with the example file. Left alone, every
# code example in the tutorial would be a dangling path.
_FASTAPI_INCLUDE = re.compile(r"^\{\*\s*(?P<path>\S+).*?\*\}[ \t]*$", re.MULTILINE)
# `## Defaults { #defaults }`: explicit anchor ids used for translations.
_HEADING_ANCHOR = re.compile(r"\s*\{\s*#[\w-]+\s*\}[ \t]*$")
# pymdown blocks: `/// tip`, `/// note | Technical Details`, `//// tab | Python 3.10+`,
# each closed by a bare `///` or `////`.
_BLOCK_OPEN = re.compile(
    r"^/{3,}[ \t]*(?P<kind>\w+)[ \t]*(?:\|[ \t]*(?P<title>.+?))?[ \t]*$", re.MULTILINE
)
_BLOCK_CLOSE = re.compile(r"^/{3,}[ \t]*\n?", re.MULTILINE)


def _block_label(match: re.Match[str]) -> str:
    kind, title = match["kind"], match["title"]
    if kind == "tab":
        return f"**{title}:**" if title else ""
    label = kind.capitalize()
    return f"**{label}: {title}**" if title else f"**{label}:**"


def _clean_headings(markdown: str) -> str:
    """Strip anchor ids and inline markup from headings outside code fences.

    Docling's Markdown backend moves inline code or emphasis in a heading into
    a child group and leaves the heading text empty, which silently merges
    adjacent sections. `#` lines inside fences are Python comments, not
    headings, and are left alone.
    """
    lines = markdown.split("\n")
    in_fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and re.match(r"#{1,6} ", line):
            heading = _HEADING_ANCHOR.sub("", line)
            lines[i] = heading.replace("`", "").replace("*", "")
    return "\n".join(lines)


def rewrite_fastapi_markdown(markdown: str, read_include: Callable[[str], str | None]) -> str:
    """Render FastAPI's mkdocs extensions as plain Markdown.

    Inlines ``{* ... *}`` example includes, strips anchor ids and inline
    markup from headings, and turns ``/// tip`` blocks into a bold label.

    ``read_include`` receives the repo-relative path (``docs_src/...``) and
    returns the file's contents, or None if it does not exist.
    """

    def inline(match: re.Match[str]) -> str:
        path = match["path"]
        repo_path = path[path.index("docs_src/") :] if "docs_src/" in path else path
        code = read_include(repo_path)
        if code is None:
            log.warning("unresolved FastAPI include: %s", path)
            return match[0]
        return f"```python\n{code.rstrip()}\n```"

    markdown = _FASTAPI_INCLUDE.sub(inline, markdown)
    markdown = _clean_headings(markdown)
    markdown = _BLOCK_OPEN.sub(_block_label, markdown)
    return _BLOCK_CLOSE.sub("", markdown)


def extract_sphinx_main(html: str) -> tuple[str, str]:
    """Return ``(title, html)`` keeping only the article of a Sphinx page.

    The full page carries a sidebar, breadcrumb navigation, "previous/next
    topic" links and a search box, all of which Docling faithfully turns into
    text that would be indexed on every page.
    """
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one('div[role="main"]') or soup.select_one("div.body")
    if main is None:
        raise ValueError("no Sphinx main content found")
    # The pilcrow permalinks after every heading.
    for link in main.select("a.headerlink"):
        link.decompose()
    # Pygments wraps every token of a code example, and every part of an API
    # signature, in its own <span>; Docling joins the spans with spaces
    # ("parser . add_argument ( 'move' )") and can lose the newlines. Collapse
    # both to plain text.
    for pre in main.select("pre"):
        pre.string = pre.get_text()
    for sig in main.select("dt.sig"):
        text = " ".join(sig.get_text().split())
        sig.clear()
        code = soup.new_tag("code")
        code.string = text
        sig.append(code)
    h1 = main.find("h1")
    if h1 is not None:
        title = h1.get_text(" ", strip=True)
    else:
        title = soup.title.get_text(strip=True) if soup.title else ""
    page = f"<html><head><title>{escape(title)}</title></head><body>{main}</body></html>"
    return title, page


def _markdown_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(raw_dir: Path, rel: Path, data: bytes) -> str:
    target = raw_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return _sha256(data)


def fetch_fastapi(src: FastApiSource, client: httpx.Client, raw_dir: Path) -> list[ManifestEntry]:
    url = f"https://codeload.github.com/fastapi/fastapi/tar.gz/refs/tags/{src.tag}"
    log.info("fastapi: downloading %s", url)
    resp = client.get(url)
    resp.raise_for_status()

    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            # Strip the "fastapi-<tag>/" prefix GitHub adds to every path.
            rel = member.name.split("/", 1)[1]
            if rel.startswith(("docs/en/docs/", "docs_src/")):
                f = tar.extractfile(member)
                if f is not None:
                    files[rel] = f.read()

    def read_include(path: str) -> str | None:
        data = files.get(path)
        return data.decode() if data is not None else None

    prefix = "docs/en/docs/"
    entries: list[ManifestEntry] = []
    for rel in sorted(files):
        if not rel.startswith(prefix) or not rel.endswith(".md"):
            continue
        doc_path = PurePosixPath(rel[len(prefix) :])
        if not any(doc_path.full_match(g) for g in src.include):
            continue
        markdown = rewrite_fastapi_markdown(files[rel].decode(), read_include)
        key = str(doc_path.with_suffix(""))
        page = "" if key == "index" else key.removesuffix("/index")
        out = Path("fastapi") / doc_path
        entries.append(
            ManifestEntry(
                doc_id=f"fastapi:{key}",
                source="fastapi",
                format=SourceFormat.MARKDOWN,
                url=f"https://fastapi.tiangolo.com/{page}/"
                if page
                else "https://fastapi.tiangolo.com/",
                title=_markdown_title(markdown, key),
                path=out,
                sha256=_write(raw_dir, out, markdown.encode()),
            )
        )
    log.info("fastapi: %d documents", len(entries))
    return entries


def fetch_pydocs(src: PyDocsSource, client: httpx.Client, raw_dir: Path) -> list[ManifestEntry]:
    entries: list[ManifestEntry] = []
    for page in src.pages:
        url = f"https://docs.python.org/{src.version}/{page}.html"
        log.info("pydocs: %s", url)
        resp = client.get(url)
        resp.raise_for_status()
        title, html = extract_sphinx_main(resp.text)
        out = Path("pydocs") / f"{page}.html"
        entries.append(
            ManifestEntry(
                doc_id=f"pydocs:{page}",
                source="pydocs",
                format=SourceFormat.HTML,
                url=url,
                title=title,
                path=out,
                sha256=_write(raw_dir, out, html.encode()),
            )
        )
    return entries


def _get_with_retry(client: httpx.Client, url: str) -> httpx.Response:
    for attempt in range(1, _ARXIV_ATTEMPTS + 1):
        resp = client.get(url)
        if resp.status_code not in _RETRY_STATUSES or attempt == _ARXIV_ATTEMPTS:
            break
        wait = ARXIV_DELAY_S * 2**attempt
        log.warning("%s -> %d, retrying in %.0fs", url, resp.status_code, wait)
        time.sleep(wait)
    resp.raise_for_status()
    return resp


def _arxiv_titles(ids: tuple[str, ...], client: httpx.Client) -> dict[str, str]:
    # The query string is built by hand: arXiv answers 406 when the commas in
    # id_list arrive percent-encoded (%2C), which is what `params=` produces.
    resp = _get_with_retry(
        client,
        f"https://export.arxiv.org/api/query?id_list={','.join(ids)}&max_results={len(ids)}",
    )
    ns = {"a": "http://www.w3.org/2005/Atom"}
    titles: dict[str, str] = {}
    for entry in ET.fromstring(resp.text).findall("a:entry", ns):
        arxiv_id = (entry.findtext("a:id", "", ns)).rsplit("/", 1)[-1]
        titles[arxiv_id] = " ".join(entry.findtext("a:title", "", ns).split())
    return titles


def fetch_arxiv(src: ArxivSource, client: httpx.Client, raw_dir: Path) -> list[ManifestEntry]:
    titles = _arxiv_titles(src.ids, client)
    missing = set(src.ids) - titles.keys()
    if missing:
        raise ValueError(f"arXiv API returned no metadata for: {sorted(missing)}")

    entries: list[ManifestEntry] = []
    for i, arxiv_id in enumerate(src.ids):
        out = Path("arxiv") / f"{arxiv_id}.pdf"
        target = raw_dir / out
        # Versioned IDs are immutable, so an existing file is reused rather
        # than spending another rate-limited request on it.
        if target.exists():
            sha = _sha256(target.read_bytes())
        else:
            if i:
                time.sleep(ARXIV_DELAY_S)
            url = f"https://arxiv.org/pdf/{arxiv_id}"
            log.info("arxiv: %s", url)
            resp = _get_with_retry(client, url)
            sha = _write(raw_dir, out, resp.content)
        entries.append(
            ManifestEntry(
                doc_id=f"arxiv:{arxiv_id}",
                source="arxiv",
                format=SourceFormat.PDF,
                url=f"https://arxiv.org/abs/{arxiv_id}",
                title=titles[arxiv_id],
                path=out,
                sha256=sha,
            )
        )
    return entries


def fetch_corpus(cfg: CorpusConfig) -> list[ManifestEntry]:
    headers = {"User-Agent": cfg.user_agent}
    with httpx.Client(headers=headers, follow_redirects=True, timeout=120.0) as client:
        entries = [
            *fetch_fastapi(cfg.fastapi, client, cfg.raw_dir),
            *fetch_pydocs(cfg.pydocs, client, cfg.raw_dir),
            *fetch_arxiv(cfg.arxiv, client, cfg.raw_dir),
        ]
    write_jsonl(cfg.raw_dir / MANIFEST_NAME, entries)
    return entries
