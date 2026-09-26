"""Tests for the span splitter and structural chunking."""

from itertools import pairwise
from pathlib import Path

import pytest
from docling.document_converter import DocumentConverter

from lemma_rag.ingest.chunk import chunk_document, split_spans
from lemma_rag.ingest.config import ChunkingConfig
from lemma_rag.ingest.models import ManifestEntry, SourceFormat

SEPS = ("\n\n", "\n", ". ", " ", "")


def _texts(text: str, size: int, overlap: int) -> list[str]:
    return [text[s:e] for s, e in split_spans(text, size, overlap, SEPS)]


def test_short_text_is_one_chunk() -> None:
    assert split_spans("hello world", 100, 10, SEPS) == [(0, 11)]


def test_empty_text_has_no_chunks() -> None:
    assert split_spans("", 100, 10, SEPS) == []


@pytest.mark.parametrize(("size", "overlap"), [(50, 0), (50, 20), (120, 30), (7, 3)])
def test_chunks_respect_size_and_cover_text(size: int, overlap: int) -> None:
    text = "\n\n".join(
        f"Paragraph {i}. " + " ".join(f"word{j}" for j in range(i * 3)) for i in range(12)
    )
    spans = split_spans(text, size, overlap, SEPS)
    assert all(e - s <= size for s, e in spans)
    # No gaps: every character is in some chunk.
    assert spans[0][0] == 0
    assert spans[-1][1] == len(text)
    for (_, prev_end), (start, _) in pairwise(spans):
        assert start <= prev_end


def test_prefers_paragraph_boundaries() -> None:
    a, b = "a" * 40, "b" * 40
    assert _texts(f"{a}\n\n{b}", 50, 0) == [f"{a}\n\n", b]


def test_overlap_repeats_whole_pieces() -> None:
    text = "One. Two. Three. Four. Five."
    # "Two. " (5 chars) fits the 6-char overlap and is repeated; "Three. " (7)
    # does not, so the third chunk starts clean rather than mid-sentence.
    assert _texts(text, 12, 6) == ["One. Two. ", "Two. Three. ", "Four. Five."]


def test_overlap_is_skipped_when_last_piece_exceeds_it() -> None:
    text = "x" * 30 + " " + "y" * 30
    assert _texts(text, 35, 5) == ["x" * 30 + " ", "y" * 30]


def test_unbreakable_text_is_hard_split() -> None:
    assert _texts("z" * 25, 10, 0) == ["z" * 10, "z" * 10, "z" * 5]


def test_rejects_separators_without_fallback() -> None:
    with pytest.raises(ValueError, match='include ""'):
        split_spans("z" * 25, 10, 0, (" ",))


def test_config_rejects_overlap_not_smaller_than_size() -> None:
    with pytest.raises(ValueError, match="chunk_overlap"):
        ChunkingConfig(chunk_size=100, chunk_overlap=100)


def test_config_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="chunk_overlp"):
        ChunkingConfig.model_validate({"chunk_overlp": 10})


MARKDOWN = """\
# Guide

Intro paragraph about the guide.

## Install

Run the installer. It takes a minute.

## Usage

First usage paragraph.

Second usage paragraph.

## References

- Some Author. Some Paper. 2020.
"""


@pytest.fixture
def entry(tmp_path: Path) -> ManifestEntry:
    (tmp_path / "guide.md").write_text(MARKDOWN)
    return ManifestEntry(
        doc_id="test:guide",
        source="test",
        format=SourceFormat.MARKDOWN,
        url="https://example.com/guide",
        title="Guide",
        path=Path("guide.md"),
        sha256="0" * 64,
    )


def _chunk(tmp_path: Path, entry: ManifestEntry, cfg: ChunkingConfig) -> list[str]:
    doc = DocumentConverter().convert(tmp_path / entry.path).document
    chunks = chunk_document(doc, entry, cfg, "fp")
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert all(c.n_chunks == len(chunks) and c.config_fingerprint == "fp" for c in chunks)
    assert all(c.chunk_id == f"test:guide#{c.chunk_index}" for c in chunks)
    return [" > ".join(c.heading_path) + " | " + c.text for c in chunks]


def test_chunks_follow_sections(tmp_path: Path, entry: ManifestEntry) -> None:
    assert _chunk(tmp_path, entry, ChunkingConfig()) == [
        "Guide | Intro paragraph about the guide.",
        "Guide > Install | Run the installer. It takes a minute.",
        "Guide > Usage | First usage paragraph.\n\nSecond usage paragraph.",
        "Guide > References | - Some Author. Some Paper. 2020.",
    ]


def test_excluded_headings_are_dropped(tmp_path: Path, entry: ManifestEntry) -> None:
    cfg = ChunkingConfig(exclude_headings=("^references$",))
    assert not any("References" in c for c in _chunk(tmp_path, entry, cfg))


def test_oversized_section_is_split_within_section(tmp_path: Path, entry: ManifestEntry) -> None:
    cfg = ChunkingConfig(chunk_size=30, chunk_overlap=0)
    chunks = _chunk(tmp_path, entry, cfg)
    usage = [c for c in chunks if c.startswith("Guide > Usage |")]
    assert usage == [
        "Guide > Usage | First usage paragraph.",
        "Guide > Usage | Second usage paragraph.",
    ]
