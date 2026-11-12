# Workspace RAG eval — wiki corpus

25 queries, 63 chunks. File-level ranking.

| Retriever | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|---|---|---|---|
| hybrid | 72% | 88% | 92% | 0.808 |
| bm25 | 64% | 88% | 88% | 0.756 |
| dense | 60% | 92% | 96% | 0.750 |

## Hybrid misses (not in top 3)

- `how do I keep everything on my machine and never call cloud models` — wanted Configuration-Reference.md, Quick-Start.md; got Architecture.md, Core-Systems.md, Changelog.md
- `steps to plug in a new language model backend` — wanted Development-Guide.md; got Core-Systems.md, Architecture.md, Tool-Registry.md
- `what are the layers of the codebase and how do they depend on each other` — wanted Architecture.md; got Configuration-Reference.md, Home.md, Core-Systems.md
