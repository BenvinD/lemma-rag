"""Chunk inspector: print a random sample of chunks, plus size statistics.

The sample is meant to be *read*. The statistics are there to point at where
to read next: a pile of tiny chunks or one source dominating the count is
usually a parsing problem, not a chunking one.
"""

import random
import statistics
from collections import Counter
from collections.abc import Sequence

from lemma_rag.ingest.models import Chunk

# Chunks shorter than this rarely answer anything on their own; it is a
# reporting threshold only and does not filter anything.
TINY_CHARS = 100


def sample_chunks(chunks: Sequence[Chunk], n: int, seed: int) -> list[Chunk]:
    """Deterministic for a given seed, so a sample can be revisited later."""
    return random.Random(seed).sample(list(chunks), min(n, len(chunks)))


def render_chunk(chunk: Chunk, position: int, total: int) -> str:
    path = " > ".join(chunk.heading_path) or "(no heading)"
    pages = f"pages {','.join(map(str, chunk.pages))}" if chunk.pages else "no pages"
    header = (
        f"[{position}/{total}] {chunk.chunk_id}  "
        f"({chunk.chunk_index + 1}/{chunk.n_chunks}, {chunk.n_chars} chars, {pages})\n"
        f"  title: {chunk.title}\n"
        f"  path:  {path}\n"
        f"  url:   {chunk.url}"
    )
    return f"{'=' * 80}\n{header}\n{'-' * 80}\n{chunk.text}\n"


def render_stats(chunks: Sequence[Chunk], chunk_size: int | None = None) -> str:
    if not chunks:
        return "no chunks"
    sizes = sorted(c.n_chars for c in chunks)
    q = statistics.quantiles(sizes, n=20) if len(sizes) > 1 else [float(sizes[0])] * 19
    by_source = Counter(c.source for c in chunks)
    docs_by_source = Counter(src for src, _ in {(c.source, c.doc_id) for c in chunks})
    lines = [
        f"chunks: {len(chunks)}  documents: {sum(docs_by_source.values())}",
        "by source: "
        + ", ".join(
            f"{s} {by_source[s]} chunks / {docs_by_source[s]} docs" for s in sorted(by_source)
        ),
        f"chars: min {sizes[0]}  p5 {q[0]:.0f}  p50 {q[9]:.0f}  p95 {q[18]:.0f}  max {sizes[-1]}",
        f"tiny (<{TINY_CHARS} chars): {sum(s < TINY_CHARS for s in sizes)}",
    ]
    if chunk_size is not None:
        lines.append(f"over chunk_size ({chunk_size}): {sum(s > chunk_size for s in sizes)}")
    fingerprints = {c.config_fingerprint for c in chunks}
    if len(fingerprints) > 1:
        lines.append(f"WARNING: mixed config fingerprints {sorted(fingerprints)}")
    return "\n".join(lines)
