"""Tests for the source normalizations applied at fetch time (no network)."""

from collections import Counter
from pathlib import Path

import httpx
import pytest

from lemma_rag.ingest import corpus
from lemma_rag.ingest.config import ArxivSource
from lemma_rag.ingest.corpus import extract_sphinx_main, rewrite_fastapi_markdown

INCLUDES = {"docs_src/query_params/tutorial001_py310.py": "from fastapi import FastAPI\n"}


def test_fastapi_include_is_inlined_as_code() -> None:
    md = "Intro\n\n{* ../../docs_src/query_params/tutorial001_py310.py hl[9] *}\n\nAfter\n"
    out = rewrite_fastapi_markdown(md, INCLUDES.get)
    assert out == "Intro\n\n```python\nfrom fastapi import FastAPI\n```\n\nAfter\n"


def test_unresolved_include_is_left_in_place() -> None:
    md = "{* ../../docs_src/missing.py *}"
    assert rewrite_fastapi_markdown(md, INCLUDES.get) == md


def test_inline_markup_is_removed_from_headings_only() -> None:
    md = (
        "## Override the `HTTPException` handler\n\n"
        "### Add *path operation* dependencies\n\n"
        "Raise `HTTPException` in a *path operation*.\n\n"
        "```python\n# openssl rand -hex 32 `quoted` { #not-an-anchor }\n```\n"
    )
    assert rewrite_fastapi_markdown(md, INCLUDES.get) == (
        "## Override the HTTPException handler\n\n"
        "### Add path operation dependencies\n\n"
        "Raise `HTTPException` in a *path operation*.\n\n"
        "```python\n# openssl rand -hex 32 `quoted` { #not-an-anchor }\n```\n"
    )


def test_heading_anchor_ids_are_stripped() -> None:
    md = "# Query Parameters { #query-parameters }\n## Defaults { #defaults }\n"
    assert rewrite_fastapi_markdown(md, INCLUDES.get) == "# Query Parameters\n## Defaults\n"


@pytest.mark.parametrize(
    ("opener", "label"),
    [
        ("/// tip", "**Tip:**"),
        ("/// note | Technical Details", "**Note: Technical Details**"),
        ("//// tab | Python 3.10+", "**Python 3.10+:**"),
    ],
)
def test_admonition_blocks_become_labels(opener: str, label: str) -> None:
    fence = opener.split(" ")[0]
    md = f"{opener}\n\nBody text.\n\n{fence}\n\nNext\n"
    assert rewrite_fastapi_markdown(md, INCLUDES.get) == f"{label}\n\nBody text.\n\n\nNext\n"


SPHINX = """<html><head><title>functools — Python docs</title></head><body>
<div class="sphinxsidebar"><h3>Previous topic</h3><a href="itertools.html">itertools</a></div>
<div class="related"><a href="genindex.html">index</a> | <a href="py-modindex.html">modules</a></div>
<div class="body" role="main">
<h1>functools — Higher-order functions<a class="headerlink" href="#x">¶</a></h1>
<p>The functools module is for higher-order functions.</p>
<dl><dt class="sig sig-object py"><span class="sig-prename">functools.</span><span class="sig-name">cache</span><span class="sig-paren">(</span><em class="sig-param"><span class="n">user_function</span></em><span class="sig-paren">)</span></dt><dd><p>Simple cache.</p></dd></dl>
<div class="highlight"><pre><span></span><span class="n">f</span><span class="p">(</span><span class="mi">1</span><span class="p">)</span>
<span class="n">g</span><span class="p">()</span></pre></div>
</div>
<div class="footer">© Copyright</div>
</body></html>"""


def test_sphinx_extract_keeps_only_main_content() -> None:
    title, html = extract_sphinx_main(SPHINX)
    assert title == "functools — Higher-order functions"
    assert "higher-order functions." in html
    for junk in ("Previous topic", "modules", "Copyright", "¶"):
        assert junk not in html
    assert "<pre>f(1)\ng()</pre>" in html
    assert "<code>functools.cache(user_function)</code>" in html


def test_sphinx_extract_rejects_non_sphinx_page() -> None:
    with pytest.raises(ValueError, match="no Sphinx main"):
        extract_sphinx_main("<html><body><p>hi</p></body></html>")


ATOM = """<feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>http://arxiv.org/abs/2005.11401v4</id><title>Retrieval-Augmented
  Generation</title></entry>
<entry><id>http://arxiv.org/abs/2004.04906v3</id><title>Dense Passage Retrieval</title></entry>
</feed>"""


def test_fetch_arxiv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(corpus.time, "sleep", lambda _: None)
    seen: list[str] = []
    pdf_attempts: Counter[str] = Counter()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if request.url.path == "/api/query":
            return httpx.Response(200, text=ATOM)
        pdf_attempts[url] += 1
        # First PDF request is throttled once, then succeeds.
        if url.endswith("2005.11401v4") and pdf_attempts[url] == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=b"%PDF " + url.encode())

    ids = ("2005.11401v4", "2004.04906v3")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        entries = corpus.fetch_arxiv(ArxivSource(ids=ids), client, tmp_path)

    # arXiv answers 406 to a percent-encoded id_list; commas must stay literal.
    assert "id_list=2005.11401v4,2004.04906v3" in seen[0]
    assert pdf_attempts["https://arxiv.org/pdf/2005.11401v4"] == 2
    assert [(e.doc_id, e.title) for e in entries] == [
        ("arxiv:2005.11401v4", "Retrieval-Augmented Generation"),
        ("arxiv:2004.04906v3", "Dense Passage Retrieval"),
    ]
    assert (tmp_path / "arxiv" / "2004.04906v3.pdf").read_bytes().startswith(b"%PDF")

    # A second fetch reuses the files on disk and only re-queries metadata.
    seen.clear()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert corpus.fetch_arxiv(ArxivSource(ids=ids), client, tmp_path) == entries
    assert len(seen) == 1
