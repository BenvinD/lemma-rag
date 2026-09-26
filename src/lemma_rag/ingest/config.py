"""Typed configuration for the corpus fetcher and the ingestion pipeline.

Both configs live in TOML under ``configs/`` so that chunk size, overlap and
the exact corpus are reviewable in a diff rather than buried in code.
"""

import hashlib
import tomllib
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    # Unknown keys are errors: a typo such as `chunk_overlp` must fail loudly
    # instead of silently falling back to the default.
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChunkingConfig(_Strict):
    # Sizes are in characters, not tokens. The embedding model (and therefore
    # the tokenizer) is not chosen yet; see ADR-101.
    chunk_size: int = Field(default=1200, gt=0)
    chunk_overlap: int = Field(default=150, ge=0)
    # Tried in order; the empty string means "split anywhere" and guarantees
    # that no chunk exceeds chunk_size.
    separators: tuple[str, ...] = ("\n\n", "\n", ". ", " ", "")
    # Case-insensitive regexes. A unit is dropped when any heading in its path
    # matches.
    exclude_headings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _overlap_smaller_than_size(self) -> Self:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) must be smaller than "
                f"chunk_size ({self.chunk_size})"
            )
        if "" not in self.separators:
            raise ValueError('separators must include "" so oversized text can always be split')
        return self


class PdfConfig(_Strict):
    # "pypdfium2" keeps inter-word spaces that "docling_parse" drops on many
    # LaTeX PDFs ("Articlesareonly clustered"), at the cost of being much
    # slower on table-heavy papers. Parses are cached, so this is paid once.
    backend: Literal["pypdfium2", "docling_parse"] = "pypdfium2"
    # arXiv PDFs are born-digital; OCR only adds minutes per document.
    do_ocr: bool = False
    do_table_structure: bool = True
    # Infer heading levels from bookmarks/numbering so PDF chunks carry a full
    # path ("3 Experiments > 3.1 Setup") instead of a flat list of headings.
    infer_heading_levels: bool = True


class IngestConfig(_Strict):
    raw_dir: Path = Path("data/raw")
    parsed_dir: Path = Path("data/parsed")
    chunks_path: Path = Path("data/chunks/chunks.jsonl")
    chunking: ChunkingConfig = ChunkingConfig()
    pdf: PdfConfig = PdfConfig()

    def fingerprint(self) -> str:
        """Short hash of the settings that change chunk output.

        Stored on every chunk so that downstream storage can tell which chunks
        were produced by an outdated configuration.
        """
        payload = self.chunking.model_dump_json() + self.pdf.model_dump_json()
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


class FastApiSource(_Strict):
    tag: str
    # Paths under docs/en/docs/, matched with Path.match-style globs.
    include: tuple[str, ...]


class PyDocsSource(_Strict):
    version: str
    pages: tuple[str, ...]


class ArxivSource(_Strict):
    # Versioned IDs (e.g. 2005.11401v4) so a re-fetch returns the same bytes.
    ids: tuple[str, ...]


class CorpusConfig(_Strict):
    raw_dir: Path = Path("data/raw")
    user_agent: str = "lemma-rag/0.1 (+https://github.com/BenvinD/lemma-rag)"
    fastapi: FastApiSource
    pydocs: PyDocsSource
    arxiv: ArxivSource


def _load[T: BaseModel](model: type[T], path: Path) -> T:
    with path.open("rb") as f:
        return model.model_validate(tomllib.load(f))


def load_ingest_config(path: Path) -> IngestConfig:
    return _load(IngestConfig, path)


def load_corpus_config(path: Path) -> CorpusConfig:
    return _load(CorpusConfig, path)
