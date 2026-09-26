# lemma-rag

**v0.4**

## What is This?

lemma-rag is a Retrieval-Augmented Generation (RAG) Agent application. It combines information retrieval with generative AI to provide contextually-informed responses. The agent retrieves relevant documents or knowledge from a corpus and uses them to augment and ground its generated output.

## About the Name

**Lemma** — In mathematics and logic, a lemma is a proven statement or established building block used as a stepping stone to prove larger theorems. We chose this name because RAG works by building responses on proven, retrieved facts—each retrieved document is a lemma (a fact-based foundation) upon which the generated response is constructed.

**RAG** — An explicit, industry-standard abbreviation for Retrieval-Augmented Generation. It immediately communicates the architectural pattern to anyone familiar with modern AI systems.

Together, **lemma-rag** combines the conceptual elegance of mathematical building blocks with the technical clarity of the RAG pattern.

## Getting Started

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.
Python 3.14 is pinned in `.python-version`.

### Installation

```bash
# Creates the virtualenv, installs the project and dev tooling from uv.lock
uv sync
```

### Running the Application

```bash
uv run uvicorn lemma_rag.rag_agent:app --reload
```

The server will be available at `http://localhost:8000`

### Corpus and Ingestion

```bash
uv run lemma fetch     # download the pinned corpus into data/raw (configs/corpus.toml)
uv run lemma ingest    # parse (Docling) -> chunk -> data/chunks/chunks.jsonl (configs/ingest.toml)
uv run lemma inspect   # print 20 random chunks + size stats; --seed N to reproduce, --source to filter
```

The corpus is 131 documents in three formats: the FastAPI tutorial (Markdown),
Python standard-library reference pages (HTML), and 30 arXiv retrieval/RAG
papers (PDF). All versions are pinned, so `lemma fetch` is reproducible.
`data/` is git-ignored.

Chunking is structural first and recursive second. Docling splits each
document into paragraphs, lists, tables and code blocks under their heading
path. Units that share a heading path form a section, and chunks never cross a
section boundary. A section larger than `chunk_size` is split recursively
(paragraph → line → sentence → word) with `chunk_overlap`. Parsed documents are
cached in `data/parsed/`, so changing chunk settings never re-parses a PDF.
Each chunk records a fingerprint of the config that produced it.

### Development

```bash
uv run pytest            # tests with coverage
uv run ruff check src tests   # lint
uv run ruff format src tests  # format
uv run mypy src          # strict type check

uv run pre-commit install    # enable hooks on commit
uv run pre-commit run --all-files
```

## Project Layout

```
src/lemma_rag/         # the package (src/ layout, not flat)
src/lemma_rag/ingest/  # corpus fetch, Docling parse, chunking, inspector
configs/               # corpus.toml (what to fetch), ingest.toml (how to chunk)
tests/                 # imports the installed package, never src/
```

The `src/` layout is deliberate. Tests import `lemma_rag` from the installed
distribution rather than from the working directory, so a packaging mistake —
a module missing from the wheel, a bad `pyproject.toml` — fails the test run
instead of being masked by Python finding the source tree first. CI enforces
this by installing a built wheel (`uv sync --no-editable`), and the pytest
config deliberately sets no `pythonpath`.

## CI/CD

Every push and pull request runs, in order:

| Stage | Command |
|-------|---------|
| Install | `uv sync --locked --no-editable` |
| Lint | `ruff check src tests` |
| Format | `ruff format --check src tests` |
| Types | `mypy src` (strict) |
| Tests | `pytest -v` |

`--locked` fails the build if `uv.lock` is out of step with `pyproject.toml`,
so dependency changes cannot land without a matching lockfile update.

The `main` branch requires these checks to pass and a pull request review.

## License

Licensed under the Apache License 2.0. See LICENSE file for details.
