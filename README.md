# lemma-rag

**v0.3**

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
src/lemma_rag/    # the package (src/ layout, not flat)
tests/            # imports the installed package, never src/
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
