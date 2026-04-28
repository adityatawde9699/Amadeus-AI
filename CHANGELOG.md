# Changelog

All notable changes to Amadeus-AI are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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
- **Local embeddings**: `QdrantMemoryService` now prioritizes `sentence-transformers/all-MiniLM-L6-v2` for memory embeddings; Gemini embedding API is a fallback only, so `LOCAL_ONLY_MODE` works fully offline.
- **Agent cycle guard**: `ReActAgent` now tracks `(action, sorted-args)` signatures per run in `_seen_action_inputs`. Repeated identical tool calls trigger an immediate synthesize-and-exit rather than looping to the iteration limit. Added the missing `_action_signature()` static helper method.

### Code Quality
- **Logging**: Replaced all eager `logger.*(f"...")` f-string calls with lazy `%s` format-arg style across `src/`. String formatting now only occurs when the log level is active.
- **Tool discovery**: Removed `globals()` introspection for tool collection. Tools are now registered via an explicit list in `container.py:_build_tool_registry()`.
- **Type safety**: Broad `Any` annotations in core service signatures replaced with proper domain types.
- **Docstrings**: `amadeus_service.py` module docstring updated to reflect the current decomposed architecture.

### Security
- **info_tools**: Replaced `eval()` with a restricted AST math evaluator for safe tool calculation.
- **Sentry**: Set `send_default_pii=False` and `traces_sample_rate=0.1` to prevent user PII leakage and reduce overhead.
- **API**: Removed the permanent unauthenticated `/sentry-debug` crash endpoint from production (now gated behind `settings.is_development`).
- **Chat**: Locked `/chat/history` endpoint behind the `current_active_user` dependency to prevent session enumeration and unauthorized access.
- **Chat**: Fixed session_id race condition in chat and SSE endpoints by binding session IDs to the authenticated user ID.
- **Prompt Injection**: Mitigated injection risks by wrapping user input explicitly inside `<user_input>` tags during LLM argument extraction.
- **IPC**: Replaced per-process IPC token generation with a persistent fallback token `data/ipc_secret.token` to ensure consistent authentication across worker restarts.

### Infrastructure
- **Alembic migrations**: Moved from blocking synchronous call to `asyncio.to_thread(command.upgrade, ...)` so migrations run without blocking the FastAPI event loop.
- **Docker**: Refactored `Dockerfile` into a 3-stage build: `builder` (deps) → `model_cache` (pre-bakes Whisper + Edge TTS) → `runtime` (slim final image). Reduces cold start from 45–90s to <5s.
- **Database**: Default `DATABASE_URL` changed from SQLite to `postgresql://postgres:postgres@localhost:5432/amadeus` in `config.py` and Docker runtime environment.

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
- **.gitignore**: Removed blanket `*.json` rule (too broad — was suppressing legitimate JSON files). Replaced with specific sensitive file patterns. Added `data/workspace_index/` exclusion.
- **.dockerignore**: Added `data/workspace_index/` exclusion.

### Fixed
- `api-prod` service in docker-compose was missing Redis dependency and `SECRET_KEY` — production deployments were silently failing quota tracking.

---

## [3.0.0] — 2026-04-19

### Added
- `LLMAdapter` abstract base class (`src/core/interfaces/llm.py`) — all provider adapters must now conform to this interface, enabling static type-checking via mypy
- `LlamaCppAdapter` now injects conversation history from `ConversationContext` into the messages list (multi-turn memory now works with local GGUF models)
- `LlamaCppAdapter` guards `flash_attn`, `type_k`, `type_v` parameters with `inspect.signature` introspection — prevents `TypeError` on older `llama-cpp-python` builds
- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md` — community health files
- GitHub Issue templates (bug report, feature request) and Pull Request template
- `CODEOWNERS` file for automatic reviewer assignment

### Fixed
- **Critical**: `memory_service.py` Qdrant upsert failure by converting points from invalid `SHA256` to deterministic `UUIDv5` values, fixing broken long-term vector persistence
- **Critical**: `sklearn` version mismatch (`InconsistentVersionWarning`); retrained SVM classifier models in the local `Model/` directory against `1.8.0` library.
- **Critical**: `LlamaCppAdapter` was raising `LLMRateLimitError` for non-rate-limit conditions (import error, model load failure, path not found), causing silent fallback to cloud providers. Now uses `ConfigurationError`, `LLMConnectionError`, and `LLMResponseError` appropriately
- **Critical**: `LLMRateLimitError` was called with full sentences as the `service` argument throughout `ollama_adapter.py` and `router.py`. Now called with the short provider identifier as intended
- `LLMRouter` class docstring now correctly reflects the actual routing priority (`LlamaCpp → Ollama → Groq → Gemini → OpenAI`) instead of the obsolete `Groq → Gemini → OpenAI`
- `container.py` Groq, Gemini, and OpenAI adapter initialization failures are now logged via `logger.warning(...)` instead of silently swallowed with `except Exception: pass`
- CI coverage gate raised from 60% to 80% to match the `pyproject.toml` `fail_under` setting
- GitGuardian CI step now has `continue-on-error: true` so a missing `GITGUARDIAN_API_KEY` secret doesn't block the entire quality pipeline

### Security
- `.env.prod`, `.env.staging`, `.env.local`, and `.env.*.local` added to `.gitignore` to prevent accidental secret commits

---

## [2.0.0] — 2026-04-17

### Added
- Clean Architecture rewrite: `src/core/`, `src/app/`, `src/infra/`, `src/api/` layers
- **LLM Router** with priority-based fallback across LlamaCpp, Ollama, Groq, Gemini, OpenAI
- **LlamaCppAdapter** — 100% offline GGUF model inference via `llama-cpp-python`
- **OllamaAdapter** — local server inference with model management (pull, list, delete)
- **GeminiAdapter** — Google Gemini 2.5 Flash via `google-genai`
- **GroqAdapter** — Groq free-tier LLM (Llama 3.3 70B)
- **OpenAIAdapter** — OpenAI GPT-4o backup for high-complexity tasks
- FastAPI REST API with JWT authentication (`fastapi-users`)
- Telegram Bot integration with webhook + long-polling support
- WhatsApp integration via Meta Cloud API
- Vector memory with ChromaDB / Qdrant for long-term semantic recall
- APScheduler background jobs for proactive assistant checks
- Prometheus metrics via `prometheus-fastapi-instrumentator`
- Sentry error tracking integration
- Redis-backed quota tracking for multi-worker LLM usage
- Docker + docker-compose for containerized deployment
- Railway deployment configuration
- GitHub Actions CI/CD pipeline (lint, type-check, test, Docker build, auto-release)
- Windows service installer (`scripts/install_windows_service.ps1`)
- Voice pipeline: Whisper STT + Edge-TTS + ElevenLabs TTS
- Tool system: filesystem, system monitoring, productivity (tasks, pomodoro, calendar)
- HITL (Human-in-the-Loop) confirmation gate for destructive tool operations
- Alembic database migrations

---

## [1.0.0] — Legacy (Amadeus/)

Initial prototype — single-file assistant with basic GPT-2/Gemini integration.

[Unreleased]: https://github.com/adityatawde9699/Amadeus-AI/compare/v3.1.0...HEAD
[3.1.0]: https://github.com/adityatawde9699/Amadeus-AI/compare/v3.0.0...v3.1.0
[3.0.0]: https://github.com/adityatawde9699/Amadeus-AI/compare/v2.0.0...v3.0.0
[2.0.0]: https://github.com/adityatawde9699/Amadeus-AI/releases/tag/v2.0.0
