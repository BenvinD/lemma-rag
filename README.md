# lemma-rag

**v0.2**

## What is This?

lemma-rag is a Retrieval-Augmented Generation (RAG) Agent application. It combines information retrieval with generative AI to provide contextually-informed responses. The agent retrieves relevant documents or knowledge from a corpus and uses them to augment and ground its generated output.

## About the Name

**Lemma** — In mathematics and logic, a lemma is a proven statement or established building block used as a stepping stone to prove larger theorems. We chose this name because RAG works by building responses on proven, retrieved facts—each retrieved document is a lemma (a fact-based foundation) upon which the generated response is constructed.

**RAG** — An explicit, industry-standard abbreviation for Retrieval-Augmented Generation. It immediately communicates the architectural pattern to anyone familiar with modern AI systems.

Together, **lemma-rag** combines the conceptual elegance of mathematical building blocks with the technical clarity of the RAG pattern.

## Getting Started

### Installation

```bash
# Install dependencies
pip install -r requirements.txt
```

### Running the Application

```bash
# Start the RAG agent server
uvicorn src.rag_agent:app --reload
```

The server will be available at `http://localhost:8000`

### Testing

```bash
# Run all tests
pytest tests/ -v

# Run tests with coverage report
pytest tests/ -v --cov=src --cov-report=html
```

## CI/CD

This repository uses GitHub Actions for continuous integration. Every push and pull request triggers:

- **Test Suite**: Python 3.10, 3.11, 3.12 compatibility testing
- **Code Quality**: Basic linting with flake8
- **Coverage**: Automated coverage tracking

The `main` branch is protected and requires:
- ✅ All CI checks to pass
- ✅ At least 1 pull request review
- ✅ No force pushes or deletions

## License

Licensed under the Apache License 2.0. See LICENSE file for details.