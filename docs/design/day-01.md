# Day 01: corpus + ingestion (DRAFT, rewrite in your own words)

**Building:** `lemma fetch` pulls a pinned, mixed-format corpus (51 FastAPI tutorial .md,
50 Python 3.14 stdlib .html, 30 arXiv RAG/retrieval .pdf = 131 docs). `lemma ingest` then runs
Docling parse → structural+recursive chunking → JSONL with metadata. `lemma inspect` samples chunks to read.

**Alternatives for chunking:**
1. Fixed-size character windows: trivial, but they cut through headings, tables and code.
2. Docling `HybridChunker`: structure-aware and token-sized, but it has no overlap and ties chunk size to a tokenizer I haven't picked yet (ADR-101).
3. Docling `HierarchicalChunker` for structure, plus my own recursive splitter for size and overlap.

**Chose 3.** Chunks never cross a heading, so `heading_path` is exact. Size and overlap live in
`configs/ingest.toml` and are measured in characters until the embedding model is chosen.
Parses are cached, so re-chunking never re-runs the PDF models. Source quirks (FastAPI `{* *}`
includes and `///` blocks, Sphinx navigation and Pygments spans) are fixed at fetch time to match what a reader of the site sees.

**PDF backend:** pypdfium2 over Docling's default docling-parse. docling-parse dropped
inter-word spaces on ~9% of arXiv chunks ("Articlesareonly clustered"). pypdfium2 fixes that, and the
full 131-doc ingest takes about the same time (5m45s vs 5m04s). Parses are cached, so re-chunking takes ~16s.
