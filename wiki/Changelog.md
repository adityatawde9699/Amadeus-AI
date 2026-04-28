# Changelog

Full version history. For detailed commit-level changes, see [CHANGELOG.md](https://github.com/adityatawde9699/Amadeus-AI/blob/main/CHANGELOG.md).

---

## v3.1.0 — Semantic Router Edition *(2026-04-22)*

### Added
- **Zero-Training Semantic Tool Router** — replaces sklearn SVM classifier, hot-pluggable, cosine similarity threshold 0.50. No retraining ever required when adding new tools.
- **Hybrid Workspace Indexer** — BM25 + dense vector retrieval fused via Reciprocal Rank Fusion. Incremental builds, context-augmented chunking. Preserves code identifiers like `AUTH_UUID_7392` as single BM25 tokens.
- **Flash Memory Cache** — Tier-1 NumPy float32 ring buffer (100 entries, ~307 KB RAM, threshold 0.85). ~1 µs vs ~5 ms Qdrant round-trip.

### Security
- Docker network isolation — Postgres (`5432`) and Redis (`6379`) ports no longer host-exposed.
- `SECRET_KEY` auto-generation via `Setup_Amadeus.bat`.
- `.dockerignore` tightened to exclude `.env` files and model weights.

---

## v3.0.0 — Clean Adapter Edition *(2026-04-19)*

### Added
- `LLMAdapter` abstract base class — all providers conform to a typed interface.
- `LlamaCppAdapter` with multi-turn memory via `ConversationContext`.
- `OllamaAdapter` with `OLLAMA_ENABLED` flag and safe connection check.

### Fixed
- Qdrant UUIDv5 upsert collision bug.
- sklearn version mismatch on Python 3.11+.
- `LlamaCppAdapter` exception type correctness (`LLMError` not `Exception`).
- numpy.py shadow file conflict causing `SemanticToolRouter` import failure.

### Quality
- Coverage gate raised to **80%**.
- `bandit` 0 HIGH gate added to CI.

---

## v2.0.0 — Clean Architecture Rewrite *(2026-04-17)*

### Added
- Full **Clean Architecture** rewrite: `core / app / infra / api` layers.
- Multi-LLM router with Redis quota tracking (Groq → Gemini → OpenAI fallback chain).
- FastAPI REST + WebSocket API with JWT auth (HS256).
- Rate limiting via SlowAPI (keyed by JWT `sub`).
- Telegram, WhatsApp, Email integrations.
- Docker + Railway deployment with multi-stage Dockerfile.
- Alembic migrations.
- APScheduler proactive loop.

---

*← [[Known-Limitations-and-Roadmap]] | [[Home]] →*
