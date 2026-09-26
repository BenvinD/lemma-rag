"""``lemma`` command line: fetch the corpus, ingest it, inspect the chunks."""

import argparse
import logging
import random
import sys
from collections.abc import Sequence
from pathlib import Path

from lemma_rag.ingest.config import load_corpus_config, load_ingest_config
from lemma_rag.ingest.inspector import render_chunk, render_stats, sample_chunks
from lemma_rag.ingest.pipeline import read_chunks, run_ingest

DEFAULT_INGEST_CONFIG = Path("configs/ingest.toml")
DEFAULT_CORPUS_CONFIG = Path("configs/corpus.toml")


def _fetch(args: argparse.Namespace) -> int:
    # Imported here so `ingest` and `inspect` do not pay for httpx/bs4.
    from lemma_rag.ingest.corpus import fetch_corpus

    entries = fetch_corpus(load_corpus_config(args.config))
    print(f"fetched {len(entries)} documents")
    return 0


def _ingest(args: argparse.Namespace) -> int:
    cfg = load_ingest_config(args.config)
    report = run_ingest(cfg, only_sources=set(args.source) if args.source else None)
    by_source = ", ".join(f"{s}: {n}" for s, n in sorted(report.chunks_by_source.items()))
    print(f"{report.documents} documents -> {report.chunks} chunks ({by_source})")
    print(f"wrote {cfg.chunks_path}  (config {cfg.fingerprint()})")
    if report.failures:
        print(f"{len(report.failures)} documents FAILED:", file=sys.stderr)
        for doc_id, reason in report.failures.items():
            print(f"  {doc_id}: {reason}", file=sys.stderr)
        return 1
    return 0


def _inspect(args: argparse.Namespace) -> int:
    cfg = load_ingest_config(args.config)
    path: Path = args.chunks or cfg.chunks_path
    chunks = [c for c in read_chunks(path) if not args.source or c.source in args.source]
    # Print the seed even when it was random, so an interesting sample can be
    # reproduced with --seed.
    seed: int = args.seed if args.seed is not None else random.randrange(1_000_000)
    sample = sample_chunks(chunks, args.n, seed)
    for i, chunk in enumerate(sample, 1):
        print(render_chunk(chunk, i, len(sample)))
    print("=" * 80)
    print(f"seed {seed}  ({path})")
    print(render_stats(chunks, cfg.chunking.chunk_size))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lemma", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="download the corpus into data/raw")
    fetch.add_argument("--config", type=Path, default=DEFAULT_CORPUS_CONFIG)
    fetch.set_defaults(func=_fetch)

    ingest = sub.add_parser("ingest", help="parse and chunk data/raw into JSONL")
    ingest.add_argument("--config", type=Path, default=DEFAULT_INGEST_CONFIG)
    ingest.add_argument(
        "--source", action="append", help="only this source (repeatable): fastapi, pydocs, arxiv"
    )
    ingest.set_defaults(func=_ingest)

    inspect = sub.add_parser("inspect", help="print a random sample of chunks")
    inspect.add_argument("--config", type=Path, default=DEFAULT_INGEST_CONFIG)
    inspect.add_argument("--chunks", type=Path, help="chunks JSONL (default: from config)")
    inspect.add_argument("-n", type=int, default=20, help="sample size (default 20)")
    inspect.add_argument("--seed", type=int, help="sampling seed (default: random, printed)")
    inspect.add_argument("--source", action="append", help="only this source (repeatable)")
    inspect.set_defaults(func=_inspect)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Docling and its model stack log every pipeline stage at INFO.
    for noisy in ("docling", "docling_core", "RapidOCR", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    sys.exit(main())
