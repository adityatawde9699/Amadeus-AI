# Changelog

All notable changes to Amadeus-AI are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [3.2.1] — 2026-04-30

### Security
- **SEC-01 — Prompt Injection Hardening:** All user task text is now wrapped in `<user_task>` XML boundary tags before being inserted into the ReAct prompt. Control tokens (`Action:`, `Thought:`, `Action Input:`, `Observation:`, `FINISH`) embedded in user input are replaced with `[BLOCKED:TOKEN]` neutralisation markers, eliminating prompt injection via messaging channels.
- **SEC-02 — WhatsApp HMAC Verification:** The `/api/v1/webhooks/whatsapp` endpoint now verifies the `X-Hub-Signature-256` header against the raw request body using `HMAC-SHA256` and the `WHATSAPP_APP_SECRET` key. Forged payloads receive HTTP 403. Added `WHATSAPP_APP_SECRET` to `Settings`.
- **SEC-03 — Telegram Authorization Guard:** `TelegramAdapter._handle_message()` now enforces a `MASTER_TELEGRAM_CHAT_ID` allowlist. Messages from any other `chat_id` receive `"Unauthorized."` and are dropped before any processing begins.
- **SEC-06 — Ephemeral SECRET_KEY Generation:** `_get_or_create_secret_key()` now auto-generates a cryptographically-secure 32-byte key at startup when `SECRET_KEY` is not set, replacing the literal `"fallback"` string. A `WARNING` is logged urging operators to set a persistent key for production. Wired into `UserManager` and `get_jwt_strategy()` in `auth/manager.py`.
- **CQ-01/02 — Filesystem Path Sandboxing:** `copy_file`, `move_file`, and `create_folder` now call `_assert_in_allowed_dirs()` which resolves the full canonical path and validates it against `SEARCH_ALLOWED_DIRS` before executing. Path traversal attempts return `"Access denied: …"` without touching the filesystem.
- **CQ-07 — History Endpoint Error Leakage:** `/api/v1/chat/history` no longer returns `str(e)` to clients. All 500 responses now return a generic `"An internal error occurred"` message while full exception details are logged server-side.

### Architecture & Reliability
- **ARCH-01 — AmadeusService DI Singleton:** `TelegramAdapter` and `webhooks.py` now reuse `global_container.amadeus_service()` instead of constructing a new `AmadeusService` per incoming message. Eliminates O(messages) Qdrant client creation and embedding model loads under load.
- **ARCH-02 — AutonomousObservationLoop DI Fix:** `_trigger_observation()` now obtains the service via `global_container.amadeus_service()` rather than raw construction, ensuring it receives the full DI-wired tool registry and LLM router.
- **ARCH-04 — Qdrant Init Race Condition:** Added `_get_qdrant_lock()` (lazy `asyncio.Lock`) around the global `AsyncQdrantClient` construction in `_setup()`. Prevents FileLock collisions when multiple concurrent `initialize()` calls race during startup.
- **DR-01 — AutonomousObservationLoop Task Tracking:** `asyncio.create_task()` result is now stored as `self._task` and `_on_task_done` done-callback is registered. Unhandled loop exceptions are logged at `ERROR` level. `stop()` cancels the task.
- **DR-02 — AgentOrchestrator Shutdown:** `AgentOrchestrator.shutdown()` is now implemented — cancels `_worker_task` and awaits it with `contextlib.suppress(CancelledError)`, eliminating zombie asyncio tasks on daemon restart.
- **DR-03 — APScheduler Graceful Shutdown:** `scheduler.shutdown(wait=False)` changed to `shutdown(wait=True)` so in-flight proactive-check jobs complete before the event loop closes, preventing partial state (e.g. half-sent notifications, open DB transactions).
- **DR-05 — IPC Token Corruption Handling:** `load_or_create_ipc_secret()` now catches `UnicodeDecodeError`, `OSError`, and empty-file cases separately. A `CRITICAL` log entry names the file path and warns that connected IPC clients will need to re-authenticate before regenerating the token.

### Agent Improvements
- **AG-01 — Secondary Cycle Detection:** Added `_action_counts` frequency counter alongside the existing `_seen_action_inputs` set. The same tool called more than 3 times with any combination of arguments now triggers the cycle guard, preventing semantic bypasses using slightly different query args.
- **AG-02 — SYNTHESIZE Success Flag:** The `SYNTHESIZE` step now examines all tool observation strings before setting `result.success`. If every observation begins with `"Error"`, `result.success` is set to `False` — the caller can now distinguish partial failures from complete success.
- **AG-03 — Parameterised Weather Location:** The hardcoded `"India"` fallback in the weather tool call is replaced with `settings.DEFAULT_LOCATION`, making the default location configurable per deployment.

### Performance
- **PC-01 — Non-Blocking Gemini Calls:** `_process_with_gemini()` now wraps the synchronous `genai.generate_content()` SDK call in `loop.run_in_executor(None, ...)`, preventing event loop blocking during LLM inference under concurrent load.
- **PC-02 — SSE Sentence-Chunk Streaming:** The SSE word-by-word fallback replaced with sentence-boundary chunking (~15 words per chunk, `asyncio.sleep(0.05)`). Reduces `asyncio.sleep()` calls from ~500 to ~25 per average response, cutting artificial streaming latency from ~5 s to ~1.25 s.
- **PC-03 — Conversation Manager Hydration:** `_get_conversation_manager()` now sets a `_db_loaded` flag after the first `load_from_db()` call, preventing redundant database reads on every subsequent request within the same service lifecycle.

### Phase 6–9 Hardening
- **P6-T5 — Redis Availability Probe:** SlowAPI rate limiter now probes Redis connectivity with a 2-second `ping()` at startup. If Redis is unreachable, the limiter falls back to in-memory storage cleanly (log warning emitted) instead of crashing the server on `Limiter()` init.
- **P6-T7 — Memory Deduplication:** `QdrantMemoryService.store()` point IDs are now derived from `uuid5(session_id:role:text)` without the timestamp, making identical message upserts idempotent. Flooding the same text N times now occupies one Qdrant slot instead of N.
- **P7-Chaos01 — Qdrant Error Metrics:** `amadeus_memory_errors_total{operation}` Prometheus counter added to `src/infra/metrics.py`. Incremented on every `upsert` and `search` Qdrant exception — failures are now visible in the `/api/v1/metrics` dashboard.
- **P7-Chaos03 — Telegram Queue Full Handling:** `QueueFullError` is caught specifically in `_process_and_reply_background()`. Sends `"⏳ I'm processing several requests right now. Please try again in a moment."` instead of a generic error, preserving error context and UX.
- **P7-Chaos04 — Migration Failure Banner:** Alembic migration failures in development mode now emit a boxed ASCII banner at `ERROR` level showing the exact error and the `alembic upgrade head` command, making schema drift immediately visible.
- **P8 — Tool Error Prose Wrapping:** When a tool dispatch returns `result.success=False`, the raw error string is now passed through `compose_tool_response()` producing a natural-language `"I tried X but encountered an error: …"` response instead of a raw exception string.

### Phase 11 — Test Suite
- **`tests/unit/test_security_hardening.py`** (new): 10 unit tests covering SEC-01, SEC-02, SEC-03, CQ-01/02, CQ-03, and P6-T7 deduplication with `pytest-asyncio`.
- **`tests/unit/test_agent_reliability.py`** (new): 10 unit tests covering AG-01 (exact + frequency cycle detection), AG-02 (SYNTHESIZE success flag), DR-01 (task tracking + done-callback + stop), DR-02 (orchestrator shutdown idempotence), DR-03 (wait=True assertion), and HITL deny-by-default.

### Phase 12 — Architecture Upgrades
- **`src/infra/messaging/protocols.py`** (new): `IMessagingAdapter` runtime-checkable `Protocol` with `verify_request`, `parse_message`, `send_reply`, `get_authorized_users`. `InboundMessage` dataclass provides platform-agnostic message normalisation across Telegram/WhatsApp/Slack.
- **`src/api/routes/readiness.py`** (new): `/api/v1/health/live` (liveness — always 200) and `/api/v1/health/ready` (readiness — checks DB, Redis, Qdrant, LLM router with per-dependency 503 detail map). Registered without auth for container orchestrator compatibility.
- **`src/infra/metrics.py`**: Added `amadeus_tool_duration_seconds` Histogram (per-tool latency, 10 buckets) and `amadeus_tool_executions_total` Counter (per-tool, per-result label) as recommended in the Phase 12 audit. Emitted from `ToolExecutor.execute()` on every success and failure path.

### Code Quality
- **CQ-03 — Tool Validation Fail-Fast:** `_validate_args()` now populates `_validation_error` sentinel in the returned dict when required parameters are absent. `execute()` checks for the sentinel before the retry loop and returns `ToolExecutionResult(success=False)` immediately, surfacing a clear `"Missing required parameter(s): …"` error instead of a cryptic `TypeError` from inside the tool function.
- **CQ-04 — Bounded Execution History:** `ToolExecutor.execution_history` changed from `list[dict]` to `deque(maxlen=500)`, capping daemon memory growth from O(runtime) to a fixed upper bound.
- **CQ-05 — Deprecated Event Loop API:** `asyncio.get_event_loop()` replaced with `asyncio.get_running_loop()` throughout `base.py`, eliminating `DeprecationWarning` on Python 3.10+ and `RuntimeError` on 3.12+.
- **CQ-06 — Duplicate Method Removed:** The duplicate `_action_signature` `@staticmethod` at `agent_loop.py:111` removed; only the documented version at line 505 is kept.

---

## [3.2.0] — 2026-04-29

### Architecture
- **AmadeusService**: Decomposed 1,381-line God-Object into five focused sub-services: `ArgumentExtractor`, `ResponseComposer`, `ToolDispatcher`, `ConversationManager`, and `UnifiedSemanticRouter`. Service is now 496 lines and acts as a thin orchestrator.
- **Tool Registry**: Removed `_register_all_tools()` from `AmadeusService`. Registry is now exclusively built and injected by the DI container — no double-registration.
- **ConversationMessage**: Eliminated duplicate model. The `@dataclass` in `conversation_manager.py` has been removed; the module now re-exports the canonical `ConversationMessage(BaseModel)` from `src.core.domain.models`. All timestamps migrated to timezone-aware `datetime.now(UTC)`.

### Performance & Stability
- **Startup**: `UnifiedSemanticRouter.build_index()` moved to `AmadeusService.initialize()` and runs in a thread pool via `run_in_executor` — FastAPI no longer blocks for 5–30s on startup.
- **Session safety**: `session_id` is now passed explicitly per request through `handle_command()` — mutating the service singleton is no longer possible.
- **Semaphore**: Removed the non-atomic `if _chat_semaphore.locked()` pre-check from the chat endpoint. `async with _chat_semaphore` alone handles concurrency correctly.
- **HTTP sessions**: `info_tools.py` and `SearchRouter` now use a single shared `aiohttp.ClientSession` per adapter, initialized at startup and closed on shutdown.

### AI / LLM System
- **Semantic router**: Threshold recalibrated from `0.38` → `0.30` for `all-MiniLM-L6-v2`. Threshold constant extracted to `_DEFAULT_THRESHOLD` for easy tuning.
- **Cloud escalation anchors**: Expanded from 6 vague phrases to 24 rich, domain-specific anchors covering debugging, architecture, distributed systems, security review, ML, and incident analysis.
- **Local embeddings**: `QdrantMemoryService` now prioritizes `sentence-transformers/all-MiniLM-L6-v2` for memory embeddings; Gemini embedding API is a fallback only.
- **Agent cycle guard**: `ReActAgent` tracks `(action, sorted-args)` signatures per run.

### Code Quality
- **Logging**: Replaced all eager `logger.*(f"…")` f-string calls with lazy `%s` format-arg style.
- **Tool discovery**: Removed `globals()` introspection. Tools registered via explicit list in `container.py`.
- **Type safety**: Broad `Any` annotations replaced with proper domain types.
- **Security**: `eval()` replaced with restricted AST math evaluator in `info_tools`; Sentry `send_default_pii=False`.

### Infrastructure
- **Alembic migrations**: Moved to `asyncio.to_thread(command.upgrade, ...)`.
- **Docker**: Refactored `Dockerfile` into a 3-stage build reducing cold start from 45–90s to <5s.
- **Database**: Default `DATABASE_URL` changed from SQLite to PostgreSQL.

---

## [3.1.0] — 2026-04-22

### Added
- **Zero-Training Semantic Tool Router** (`src/app/services/semantic_router.py`): Replaced sklearn SVM classifier with `sentence-transformers/all-mpnet-base-v2` cosine similarity routing. Supports hot-pluggable tool registration with zero retraining. Confidence threshold: `0.50`; falls back to LlamaCpp LLM router below threshold.
- **Hybrid Workspace Indexer** (`src/infra/workspace_indexer.py`): Dense vector (all-mpnet-base-v2) + BM25 (rank-bm25) retrieval fused via Reciprocal Rank Fusion (RRF, k=60). Supports incremental builds (mtime + MD5 content hash), `max_chunks` cap (default 15,000 ≈ 66 MB RAM), `mmap_mode='r'` loading, and context-augmented chunking.
- **Context-Augmented Chunking**: File-level metadata header (imports, globals, titles, section names) prepended to embedding input — not stored in display snippets. Improves semantic vector quality for code QA without polluting BM25 or search results.
- **Workspace Search Tool** (`src/infra/tools/workspace_tools.py`): Amadeus tool `search_workspace` enabling autonomous semantic search over the local project repository.
- **Flash Memory Cache** (`FlashMemoryCache` in `src/infra/memory_service.py`): Tier-1 in-process ring buffer (100 entries, 307 KB, NumPy float32). Intercepts `QdrantMemoryService.retrieve()` calls with cosine similarity check (threshold `0.85`). Cache hit skips Qdrant entirely (~microsecond vs ~5ms). Invalidated on `clear_session()`.
- **Workspace Indexer CLI** (`scripts/index_workspace.py`): `--root`, `--force`, `--max-chunks`, `--quiet` flags. Default root: `C:\Users\ASUS\Downloads`.
- `rank-bm25>=0.2.2` added to core dependencies.

### Security
- **docker-compose.yml**: Removed hardcoded `amadeus_password` — Postgres password now sourced from `${POSTGRES_PASSWORD:-amadeus_password}`.
- **docker-compose.yml**: Removed Redis host port exposure (`6379:6379`). Redis is now internal to `amadeus-network` only.
- **docker-compose.yml**: Removed Postgres host port exposure (`5432:5432`). DB is now internal to `amadeus-network` only.
- **docker-compose.yml**: `api-prod` now correctly inherits `REDIS_URL` and `SECRET_KEY`; added `depends_on: redis`.
- **Dockerfile**: Replaced `.env*` glob COPY with explicit `.env.example` only — prevents `.env.prod`/`.env.staging` from being baked into image layers.
- **Setup_Amadeus.bat**: Auto-generates `SECRET_KEY` via `secrets.token_hex(32)` and writes it to `.env`. Added security reminder banner.
- **Start_Amadeus.bat**: Added `.env` pre-flight check — fails fast if setup hasn't been run.
- **SECURITY.md**: Updated to v3.x support matrix; added Docker network isolation and workspace index privacy notes.
- **.gitignore**: Removed blanket `*.json` rule. Replaced with specific sensitive file patterns. Added `data/workspace_index/` exclusion.
- **.dockerignore**: Added `data/workspace_index/` exclusion.

### Fixed
- `api-prod` service in docker-compose was missing Redis dependency and `SECRET_KEY` — production deployments were silently failing quota tracking.

---

## [3.0.0] — 2026-04-19

### Added
- `LLMAdapter` abstract base class (`src/core/interfaces/llm.py`) — all provider adapters must now conform to this interface, enabling static type-checking via mypy
- `LlamaCppAdapter` now injects conversation history from `ConversationContext` into the messages list (multi-turn memory now works with local GGUF models)
- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md` — community health files
- GitHub Issue templates (bug report, feature request) and Pull Request template
- `CODEOWNERS` file for automatic reviewer assignment

### Fixed
- **Critical**: `memory_service.py` Qdrant upsert failure by converting points from invalid `SHA256` to deterministic `UUIDv5` values
- **Critical**: `sklearn` version mismatch (`InconsistentVersionWarning`); retrained SVM classifier models against `1.8.0`
- **Critical**: `LlamaCppAdapter` was raising `LLMRateLimitError` for non-rate-limit conditions; now uses `ConfigurationError`, `LLMConnectionError`, and `LLMResponseError` appropriately
- CI coverage gate raised from 60% to 80%

### Security
- `.env.prod`, `.env.staging`, `.env.local`, and `.env.*.local` added to `.gitignore`

---

## [2.0.0] — 2026-04-17

### Added
- Clean Architecture rewrite: `src/core/`, `src/app/`, `src/infra/`, `src/api/` layers
- **LLM Router** with priority-based fallback across LlamaCpp, Ollama, Groq, Gemini, OpenAI
- FastAPI REST API with JWT authentication (`fastapi-users`)
- Telegram Bot integration with webhook + long-polling support
- WhatsApp integration via Meta Cloud API
- Vector memory with ChromaDB / Qdrant for long-term semantic recall
- APScheduler background jobs for proactive assistant checks
- Prometheus metrics via `prometheus-fastapi-instrumentator`
- Sentry error tracking integration
- Docker + docker-compose for containerized deployment
- GitHub Actions CI/CD pipeline (lint, type-check, test, Docker build, auto-release)
- Voice pipeline: Whisper STT + Edge-TTS + ElevenLabs TTS
- HITL (Human-in-the-Loop) confirmation gate for destructive tool operations
- Alembic database migrations

---

## [1.0.0] — Legacy (Amadeus/)

Initial prototype — single-file assistant with basic GPT-2/Gemini integration.

[3.2.1]: https://github.com/adityatawde9699/Amadeus-AI/compare/v3.2.0...v3.2.1
[3.2.0]: https://github.com/adityatawde9699/Amadeus-AI/compare/v3.1.0...v3.2.0
[3.1.0]: https://github.com/adityatawde9699/Amadeus-AI/compare/v3.0.0...v3.1.0
[3.0.0]: https://github.com/adityatawde9699/Amadeus-AI/compare/v2.0.0...v3.0.0
[2.0.0]: https://github.com/adityatawde9699/Amadeus-AI/releases/tag/v2.0.0
