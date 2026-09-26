"""parse -> chunk -> attach metadata -> write JSONL."""

import logging
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from lemma_rag.ingest.chunk import chunk_document
from lemma_rag.ingest.config import IngestConfig
from lemma_rag.ingest.models import Chunk, ManifestEntry
from lemma_rag.ingest.parse import Parser

log = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.jsonl"


@dataclass
class IngestReport:
    documents: int = 0
    chunks: int = 0
    chunks_by_source: Counter[str] = field(default_factory=Counter)
    failures: dict[str, str] = field(default_factory=dict)


def read_manifest(path: Path) -> list[ManifestEntry]:
    with path.open() as f:
        return [ManifestEntry.model_validate_json(line) for line in f if line.strip()]


def write_jsonl(path: Path, records: Iterable[Chunk | ManifestEntry]) -> None:
    """Write atomically, so an interrupted run never leaves a truncated file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        for r in records:
            f.write(r.model_dump_json() + "\n")
    tmp.replace(path)


def read_chunks(path: Path) -> Iterator[Chunk]:
    with path.open() as f:
        for line in f:
            if line.strip():
                yield Chunk.model_validate_json(line)


def run_ingest(cfg: IngestConfig, only_sources: set[str] | None = None) -> IngestReport:
    entries = read_manifest(cfg.raw_dir / MANIFEST_NAME)
    if only_sources:
        entries = [e for e in entries if e.source in only_sources]

    parser = Parser(cfg.pdf, cfg.raw_dir, cfg.parsed_dir)
    fingerprint = cfg.fingerprint()
    report = IngestReport()
    chunks: list[Chunk] = []

    for n, entry in enumerate(entries, 1):
        try:
            doc = parser.parse(entry)
            doc_chunks = chunk_document(doc, entry, cfg.chunking, fingerprint)
        except Exception as exc:
            # One bad document must not sink a 150-document run; the failure
            # is reported and turns into a non-zero exit code.
            log.exception("failed: %s", entry.doc_id)
            report.failures[entry.doc_id] = f"{type(exc).__name__}: {exc}"
            continue
        if not doc_chunks:
            log.warning("%s produced no chunks", entry.doc_id)
        log.info("[%d/%d] %s -> %d chunks", n, len(entries), entry.doc_id, len(doc_chunks))
        chunks.extend(doc_chunks)
        report.documents += 1
        report.chunks_by_source[entry.source] += len(doc_chunks)

    report.chunks = len(chunks)
    write_jsonl(cfg.chunks_path, chunks)
    return report
