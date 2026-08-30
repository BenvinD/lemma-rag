# Architecture Decision Records

One ADR per decision, 6–10 lines. Written *after* the decision, *before* moving on.
Copy `000-template.md` to `NNN-short-title.md` and fill it in.

These are the interview answers. If a decision has no ADR, it will not survive
being questioned six weeks from now.

## Index

This repo is the RAG system (Docent), which owns the `1xx` range.

| # | Decision | Chose | Rejected | When the rejected option wins |
|---|----------|-------|----------|-------------------------------|
| 101 | Embedding model | | | |
| 102 | Sparse engine (Qdrant vs OpenSearch) | | | |
| 103 | Reranker choice/depths | | | |
| 104 | Agent framework | | | |
| 105 | Ragas vs hand-rolled metrics | | | |
| 106 | Judge model/family | | | |
| 107 | CI gate thresholds | | | |

Fill each row as the ADR lands. The `0xx` range belongs to the gateway repo.
