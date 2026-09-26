"""Docling parsing with an on-disk cache of parsed documents.

PDF conversion runs layout and table models and takes seconds to minutes per
paper. Chunking is what gets tuned, so parsed ``DoclingDocument``s are cached
as JSON and a chunk-size change never re-parses anything.
"""

import hashlib
import logging
from pathlib import Path

from docling.backend.docling_parse_backend import ThreadedDoclingParseDocumentBackend
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import HeadingHierarchyOptions, PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc.document import DoclingDocument

from lemma_rag.ingest.config import PdfConfig
from lemma_rag.ingest.models import ManifestEntry

log = logging.getLogger(__name__)


def build_converter(cfg: PdfConfig) -> DocumentConverter:
    pdf_options = PdfPipelineOptions(
        do_ocr=cfg.do_ocr,
        do_table_structure=cfg.do_table_structure,
        heading_hierarchy_options=HeadingHierarchyOptions(enabled=cfg.infer_heading_levels),
    )
    backend = (
        PyPdfiumDocumentBackend
        if cfg.backend == "pypdfium2"
        else ThreadedDoclingParseDocumentBackend
    )
    return DocumentConverter(
        allowed_formats=[InputFormat.MD, InputFormat.HTML, InputFormat.PDF],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options, backend=backend)
        },
    )


def cache_path(entry: ManifestEntry, cfg: PdfConfig, parsed_dir: Path) -> Path:
    # Keyed on the source bytes and the parser settings: either changing
    # invalidates the cached parse.
    key = hashlib.sha256((entry.sha256 + cfg.model_dump_json()).encode()).hexdigest()[:16]
    slug = entry.doc_id.replace(":", "__").replace("/", "_")
    return parsed_dir / f"{slug}.{key}.json"


class Parser:
    """Parses manifest entries, reusing cached results where possible."""

    def __init__(self, cfg: PdfConfig, raw_dir: Path, parsed_dir: Path) -> None:
        self._cfg = cfg
        self._raw_dir = raw_dir
        self._parsed_dir = parsed_dir
        # Built on first cache miss: constructing it loads models.
        self._converter: DocumentConverter | None = None

    def parse(self, entry: ManifestEntry) -> DoclingDocument:
        cached = cache_path(entry, self._cfg, self._parsed_dir)
        if cached.exists():
            return DoclingDocument.load_from_json(cached)

        if self._converter is None:
            self._converter = build_converter(self._cfg)
        log.info("parsing %s", entry.doc_id)
        doc = self._converter.convert(self._raw_dir / entry.path).document

        cached.parent.mkdir(parents=True, exist_ok=True)
        tmp = cached.with_suffix(".tmp")
        doc.save_as_json(tmp)
        tmp.replace(cached)
        return doc
