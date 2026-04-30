# Changelog

Full version history. For detailed commit-level changes, see [CHANGELOG.md](https://github.com/adityatawde9699/Amadeus-AI/blob/main/CHANGELOG.md).

---

## v3.2.1 — Security Hardening & Observability Edition *(2026-04-30)*

### Security
- **SEC-01** — Prompt injection resistance: `<user_task>` XML boundaries + `[BLOCKED:TOKEN]` neutralisation for ReAct control tokens
- **SEC-02** — WhatsApp `X-Hub-Signature-256` HMAC verification; forged payloads → HTTP 403
- **SEC-03** — Telegram `MASTER_TELEGRAM_CHAT_ID` allowlist; unknown senders → `"Unauthorized."`
- **SEC-06** — `SECRET_KEY` auto-generates cryptographically-secure ephemeral key; no more `"fallback"` literal
- **CQ-01/02** — `copy_file`, `move_file`, `create_folder` enforce `SEARCH_ALLOWED_DIRS` via `_assert_in_allowed_dirs()`

### Reliability
- **ARCH-04** — `asyncio.Lock()` prevents Qdrant client FileLock collision during concurrent startup
- **DR-01** — Autonomous loop task stored + done-callback registered; `stop()` cancels it
- **DR-02** — `AgentOrchestrator.shutdown()` implemented; no more zombie asyncio tasks on restart
- **DR-03** — APScheduler uses `shutdown(wait=True)`; in-flight jobs complete before event loop closes
- **DR-05** — IPC token corruption (non-UTF-8, empty, OS error) caught specifically with `CRITICAL` log before regeneration

### Observability
- `/api/v1/health/live` — liveness probe (always 200)
- `/api/v1/health/ready` — readiness probe (checks DB, Redis, Qdrant, LLM; returns 503 with per-dependency map)
- `amadeus_tool_duration_seconds{tool_name,success}` Histogram — per-tool latency
- `amadeus_tool_executions_total{tool_name,result}` Counter — per-tool result breakdown
- `amadeus_memory_errors_total{operation}` Counter — Qdrant failure visibility

### Architecture
- `IMessagingAdapter` Protocol + `InboundMessage` dataclass in `src/infra/messaging/protocols.py`
- `P6-T7`: Memory deduplication via `uuid5(session_id:role:text)` — idempotent upserts
- `P7-Chaos03`: `QueueFullError` caught in Telegram background handler → friendly "busy" reply
- `PC-02`: SSE word-by-word → sentence-chunk streaming (~15 words, 4× fewer sleep calls)

### Tests
- 20 new unit tests: `test_security_hardening.py` + `test_agent_reliability.py`

---

## v3.2.0 — Production Architecture Edition *(2026-04-29)*

### Architecture
- `AmadeusService` decomposed from 1,381-line God-Object → 5 focused sub-services
- `ToolRegistry` exclusively built by DI container — no double-registration
- `ConversationMessage` model unified across the codebase

### Performance
- Semantic router index built in thread pool — no blocking startup
- `asyncio.get_event_loop()` → `asyncio.get_running_loop()` throughout
- `execution_history` bounded to `deque(maxlen=500)`

### Security
- `eval()` replaced with restricted AST math evaluator
- `/chat/history` locked behind `current_active_user`
- Sentry `send_default_pii=False`

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
