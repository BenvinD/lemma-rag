"""Structural + recursive chunking.

Two passes, each doing the thing it is good at:

1. **Structural.** Docling's ``HierarchicalChunker`` walks the parsed document
   and yields one unit per paragraph, list, table or code block, each tagged
   with its heading path. Consecutive units under the same heading path form a
   *section*. Chunks never cross a section boundary, so a chunk is always about
   one topic and its ``heading_path`` is exact.
2. **Recursive.** A section longer than ``chunk_size`` is split on the first
   separator that occurs in it (paragraph, line, sentence, word, character),
   recursing into any piece that is still too long, and the pieces are then
   packed back into windows of at most ``chunk_size`` with ``chunk_overlap``.

The splitter works on character spans rather than strings so that each chunk
can be mapped back to the units it came from, and from there to PDF pages.
"""

import re
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass

from docling_core.transforms.chunker.doc_chunk import DocChunk
from docling_core.transforms.chunker.hierarchical_chunker import HierarchicalChunker
from docling_core.types.doc.document import DoclingDocument

from lemma_rag.ingest.config import ChunkingConfig
from lemma_rag.ingest.models import Chunk, ManifestEntry

type Span = tuple[int, int]

# Units inside a section are joined with this, which is also the first default
# separator: unit boundaries are the preferred split points.
_UNIT_JOIN = "\n\n"


def split_spans(
    text: str, chunk_size: int, chunk_overlap: int, separators: Sequence[str]
) -> list[Span]:
    """Split ``text`` into ``(start, end)`` windows of at most ``chunk_size`` chars.

    Consecutive windows share up to ``chunk_overlap`` characters. Overlap is
    made of whole pieces (paragraphs, sentences, ...), so it can be smaller
    than requested, or zero when the last piece alone is longer than the
    overlap. It is never cut mid-word.
    """
    if not text:
        return []
    pieces = _atomize(text, 0, len(text), separators, chunk_size)
    return _pack(pieces, chunk_size, chunk_overlap)


def _atomize(text: str, start: int, end: int, separators: Sequence[str], size: int) -> list[Span]:
    """Cut ``text[start:end]`` into contiguous spans, none longer than ``size``."""
    if end - start <= size:
        return [(start, end)]
    for i, sep in enumerate(separators):
        if sep == "":
            return [(s, min(s + size, end)) for s in range(start, end, size)]
        if text.find(sep, start, end) != -1:
            rest = separators[i + 1 :]
            break
    else:
        # ChunkingConfig guarantees "" is present; direct callers may not.
        raise ValueError('separators must include "" to split text without a separator')

    spans: list[Span] = []
    pos = start
    while pos < end:
        hit = text.find(sep, pos, end)
        # The separator stays attached to the piece before it, so spans remain
        # contiguous and joining them reproduces the original text exactly.
        piece_end = end if hit == -1 else hit + len(sep)
        if piece_end - pos <= size:
            spans.append((pos, piece_end))
        else:
            spans.extend(_atomize(text, pos, piece_end, rest, size))
        pos = piece_end
    return spans


def _pack(pieces: list[Span], size: int, overlap: int) -> list[Span]:
    """Greedily merge contiguous pieces into windows, carrying a tail of overlap."""
    windows: list[Span] = []
    current: deque[Span] = deque()
    for piece in pieces:
        if current and piece[1] - current[0][0] > size:
            windows.append((current[0][0], current[-1][1]))
            # Keep the longest tail that fits in the overlap budget and still
            # leaves room for the incoming piece.
            while current and (
                current[-1][1] - current[0][0] > overlap or piece[1] - current[0][0] > size
            ):
                current.popleft()
        current.append(piece)
    if current:
        windows.append((current[0][0], current[-1][1]))
    return windows


@dataclass(frozen=True)
class _Unit:
    text: str
    pages: frozenset[int]


@dataclass
class _Section:
    headings: tuple[str, ...]
    units: list[_Unit]


def _sections(doc: DoclingDocument, exclude: Sequence[re.Pattern[str]]) -> list[_Section]:
    sections: list[_Section] = []
    for raw in HierarchicalChunker().chunk(doc):
        if not isinstance(raw, DocChunk):  # pragma: no cover - HierarchicalChunker contract
            raise TypeError(f"expected DocChunk, got {type(raw).__name__}")
        text = raw.text.strip()
        if not text:
            continue
        headings = tuple(h.strip() for h in raw.meta.headings or [])
        if any(p.search(h) for p in exclude for h in headings):
            continue
        pages = frozenset(prov.page_no for item in raw.meta.doc_items for prov in item.prov)
        unit = _Unit(text=text, pages=pages)
        if sections and sections[-1].headings == headings:
            sections[-1].units.append(unit)
        else:
            sections.append(_Section(headings=headings, units=[unit]))
    return sections


def chunk_document(
    doc: DoclingDocument, entry: ManifestEntry, cfg: ChunkingConfig, fingerprint: str
) -> list[Chunk]:
    exclude = [re.compile(p, re.IGNORECASE) for p in cfg.exclude_headings]
    drafts: list[tuple[tuple[str, ...], str, list[int]]] = []

    for section in _sections(doc, exclude):
        text = _UNIT_JOIN.join(u.text for u in section.units)
        unit_spans: list[tuple[Span, frozenset[int]]] = []
        pos = 0
        for u in section.units:
            unit_spans.append(((pos, pos + len(u.text)), u.pages))
            pos += len(u.text) + len(_UNIT_JOIN)

        for start, end in split_spans(text, cfg.chunk_size, cfg.chunk_overlap, cfg.separators):
            body = text[start:end].strip()
            if not body:
                continue
            pages = sorted(
                set().union(*(p for (us, ue), p in unit_spans if us < end and ue > start))
            )
            drafts.append((section.headings, body, pages))

    return [
        Chunk(
            chunk_id=f"{entry.doc_id}#{i}",
            doc_id=entry.doc_id,
            source=entry.source,
            format=entry.format,
            url=entry.url,
            title=entry.title,
            heading_path=list(headings),
            pages=pages,
            chunk_index=i,
            n_chunks=len(drafts),
            n_chars=len(body),
            text=body,
            config_fingerprint=fingerprint,
        )
        for i, (headings, body, pages) in enumerate(drafts)
    ]
