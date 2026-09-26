"""Records written to disk by the fetcher and the ingestion pipeline."""

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class SourceFormat(StrEnum):
    MARKDOWN = "md"
    HTML = "html"
    PDF = "pdf"


class ManifestEntry(BaseModel):
    """One fetched source document; a line of ``data/raw/manifest.jsonl``."""

    model_config = ConfigDict(frozen=True)

    doc_id: str  # "<source>:<stable key>", e.g. "arxiv:2005.11401v4"
    source: str  # corpus the document came from: fastapi | pydocs | arxiv
    format: SourceFormat
    url: str
    title: str
    path: Path  # relative to the raw directory
    sha256: str


class Chunk(BaseModel):
    """One retrievable unit; a line of the chunks JSONL."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str  # "<doc_id>#<chunk_index>"
    doc_id: str
    source: str
    format: SourceFormat
    url: str
    title: str
    heading_path: list[str]
    # 1-based page numbers the chunk spans; empty for formats without pages.
    pages: list[int]
    chunk_index: int
    n_chunks: int
    n_chars: int
    text: str
    # IngestConfig.fingerprint() at the time the chunk was produced.
    config_fingerprint: str
