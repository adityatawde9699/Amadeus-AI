# Changelog

All notable changes to Amadeus-AI are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [5.0.0] — 2026-06-10

### Architecture & Capabilities
- **MCP Tool Integration (Phase 3)** — Amadeus now dynamically discovers and consumes external tool capabilities via the Model Context Protocol (e.g. `filesystem`, `github`, `postgres`).
- **24/7 Daemon Hardening (Phase 6)** — Systemd daemon fully fortified with memory/CPU quotas, burst restarts, and proper ASGI SIGTERM signal handling.
- **Proactive Garbage Collection** — Background autonomous loops now correctly invoke `prune_stale_memories` to prevent Turbovec index bloating on long-lived master sessions.

---

## [5.0.0-alpha] — 2026-06-09 *(pre-release)*

### Architecture
- **Cognitive Core (Phase 1)** — Fully migrated to a deterministic `LangGraph` async state machine, resolving brittle ReAct loop parsing errors.
- **Deep RAG Memory (Phase 2)** — Replaced Qdrant with `Turbovec` + `aiosqlite`. Achieved massive 4-bit quantization compression (up to 16x scale reduction) with zero penalties, while running entirely in-process.

---

## [4.0.0] — 2026-05-29

### Architecture
- **Cognitive Core:** Replaced implicit ReAct loops with a deterministic async state machine. The system now transitions through `RECEIVED`, `PLANNING`, `EXECUTING`, `VERIFYING`, `REFLECTING`, and `DONE` states.
- **Explicit Execution Graphs:** Introduced `Plan`, `PlanStep`, `Observation`, and `Reflection` domain models. Tasks are now decomposed into persistent, auditable, and resumable data structures.
- **Dynamic Plugin System:** Tools can now be hot-loaded from a `plugins/` directory. Supports both `@tool` decorator discovery and explicit `register_tools` hooks.
- **Durable Episodic Memory:** Implemented `SQLAlchemyCognitiveRepository` to persist every stage of the cognitive lifecycle in PostgreSQL.

### Security & Safety
- **Tool Policy Engine:** Centralized security layer that evaluates `RiskLevel` and `PermissionProfile` before any tool execution.
- **Local Sandbox:** Added `LocalSandboxExecutor` using Python's `multiprocessing` for Docker-free environments. Auto-detects Docker and falls back gracefully.
- **Protected Processes:** Policy engine now explicitly blocks termination of critical system processes (e.g., `explorer.exe`).
- **Network Diagnostics:** New tools `get_network_info` and `ping_host` for system transparency.

### Features
- **Agent Self-Awareness:** Added `manage_plugins` (agent can add its own tools) and `search_codebase` (agent can inspect its own implementation).
- **Proactive Monitoring:** Enhanced autonomous loop to monitor CPU, RAM, and Battery health, proactively alerting the user on critical events.
- **Structured LLM Mode:** Updated `LLMRouter` to support a `structured` parameter, strictly enforcing JSON output for high-precision argument extraction.
- **Unified Messaging:** Centralized `MessagingService` managing Telegram and Email transports.

### Reliability
- **Verification State:** Dedicated lifecycle stage for verifying tool outputs against success criteria.
- **Circuit Breaker Integration:** Enhanced tool dispatcher with circuit breakers to prevent cascading failures during API outages.

---

## [3.2.2] — 2026-05-27

### Architecture
- **Transport Layer Refactor:** Replaced `src/api/server.py` monolith with discrete transport modules. `src/transports/fastapi_transport.py` owns FastAPI app factory and ASGI lifecycle; `src/transports/cli_transport.py` provides a direct CLI entry point; `src/transports/telegram_transport.py` handles the Telegram webhook adapter.
- **Voice Service Removed:** Removed `VoiceService`, `WhisperVoiceInput`, `EdgeTTSAdapter`, and all STT/TTS wiring from the DI container and `AmadeusService`. Voice pipeline dependencies have been excised from `container.py`.
- **Goal Management (Phase 4):** Added `Goal` domain model and `GoalStatus` enumeration. Implemented `SQLAlchemyGoalRepository` with full CRUD and status-based retrieval. Registered `create_goal`, `update_goal`, and `list_active_goals` as LLM-callable tools in `agent_tools.py`. Added Alembic migration for the `goals` table.
- **Model Manager (`src/infra/model_manager.py`):** New module that resolves local model paths and auto-downloads from HuggingFace when a model is missing. Embedding models are stored in `Model/embed/<name>/` via `snapshot_download`; GGUF files land in `Model/<filename>` via `hf_hub_download`.

### Configuration
- **`MODEL_DIR`** — Defaults to `<project>/Model/`. Override with an absolute path.
- **`MODEL_DOWNLOAD_ENABLED`** — Set `true` to auto-fetch missing models on first run (default: `true`).
- **`EMBED_MODEL_NAME`** — HuggingFace model ID for the embedding model (default: `sentence-transformers/all-MiniLM-L6-v2`).
- **`SLM_MODEL_REPO_ID` / `SLM_MODEL_FILENAME`** — HuggingFace repo and filename for GGUF auto-download. `SLM_MODEL_PATH` still takes full priority when set.
- **`PROACTIVE_MESSAGE_LIMIT_PER_HOUR`** — Rate limit for autonomous proactive observations per session (default: `3`).
- **`PROACTIVE_DRY_RUN`** — When `true`, proactive observations log intent without dispatching to transport (default: `false`).
- **`ASSISTANT_VERSION`** bumped to `3.2.2`.

### Fixes
- **Stale `src/api/server import scheduler`** removed from `agent_tools.py`; `schedule_future_task` now uses `asyncio.create_task` + `asyncio.sleep` delay.
- **`_build_voice_service` and `voice_service` singleton** removed from `container.py`; `get_voice_service()` bridge removed.
- **`from src.core.config import Settings`** under `TYPE_CHECKING` in `model_manager.py` replaced with relative import `from ..core.config import Settings` to resolve Pylance module resolution error.
- **`AgentOrchestrator` worker task** now only created inside an event loop (`auto_start=True`); bare sync container probe no longer raises `RuntimeError: no running event loop`.

### Repository Hygiene
- Removed stale root files: `check_db.py`, `debug_telegram.py`, `uvicorn` (empty file), `railway.toml`, `locustfile.py`, `.env.prod`, `.env.staging`.
- Removed `scratch/` and `wiki-publish/` directories.

### Deployment
- **`docker-compose.yml`** created declaring `amadeus`, `worker` (Arq), `postgres`, `redis`, `qdrant`, and `jaeger` services with persistent volume mapping.
- **`deploy/amadeus.service`** systemd unit file for bare-metal Linux deployment.

---

## [3.2.1] — 2026-04-30

### Security
- **SEC-01 — Prompt Injection Hardening:** User task text wrapped in `<user_task>` XML boundary tags; control tokens neutralised with `[BLOCKED:TOKEN]`.
- **SEC-02 — WhatsApp HMAC Verification:** Webhook verifies `X-Hub-Signature-256` via HMAC-SHA256; forged payloads receive HTTP 403.
- **SEC-03 — Telegram Authorization Guard:** `MASTER_TELEGRAM_CHAT_ID` allowlist enforced; unknown senders dropped before processing.
- **SEC-06 — Ephemeral SECRET_KEY Generation:** Auto-generates a cryptographically-secure 32-byte key when `SECRET_KEY` is unset.
- **CQ-01/02 — Filesystem Path Sandboxing:** `copy_file`, `move_file`, `create_folder` enforce `SEARCH_ALLOWED_DIRS` via `_assert_in_allowed_dirs()`.
- **CQ-07 — History Endpoint Error Leakage:** `/api/v1/chat/history` no longer returns raw exception strings to clients.

### Architecture & Reliability
- **ARCH-01** — `TelegramAdapter` reuses `global_container.amadeus_service()` singleton.
- **ARCH-04** — `asyncio.Lock()` around Qdrant client construction prevents init race condition.
- **DR-01** — `AutonomousObservationLoop` stores task reference and registers done-callback.
- **DR-02** — `AgentOrchestrator.shutdown()` cancels worker task cleanly.
- **DR-03** — `APScheduler.shutdown(wait=True)` prevents partial state on restart.

### Agent & Performance
- **AG-01** — Secondary cycle detection via `_action_counts` frequency counter.
- **AG-02** — `SYNTHESIZE` step sets `result.success=False` if all observations begin with `"Error"`.
- **PC-01** — Gemini calls wrapped in `run_in_executor` — non-blocking.
- **PC-02** — SSE streaming switched to sentence-boundary chunking (~15 words/chunk).

### Phase 11–12
- 20 new unit tests in `test_security_hardening.py` and `test_agent_reliability.py`.
- `IMessagingAdapter` Protocol added (`src/infra/messaging/protocols.py`).
- Health probes: `/api/v1/health/live` and `/api/v1/health/ready`.
- Per-tool Prometheus metrics: `amadeus_tool_duration_seconds`, `amadeus_tool_executions_total`, `amadeus_memory_errors_total`.

---

## [3.2.0] — 2026-04-29

### Architecture
- **AmadeusService** decomposed from 1,381-line God-Object into five focused sub-services: `ArgumentExtractor`, `ResponseComposer`, `ToolDispatcher`, `ConversationManager`, `UnifiedSemanticRouter`.
- Tool Registry exclusively built and injected by the DI container.
- `ConversationMessage` duplicate removed; module now re-exports canonical model from `src.core.domain.models`.

### Performance & Stability
- `UnifiedSemanticRouter.build_index()` moved to `AmadeusService.initialize()`, runs in thread pool.
- `session_id` passed explicitly per request — service singleton no longer mutated.
- Shared `aiohttp.ClientSession` per adapter, initialized at startup.

### AI / LLM
- Semantic router threshold recalibrated from `0.38` → `0.30` for `all-MiniLM-L6-v2`.
- Cloud escalation anchors expanded from 6 to 24 domain-specific examples.

---

## [3.1.0] — 2026-04-22

### Added
- **Zero-Training Semantic Tool Router** — `sentence-transformers/all-mpnet-base-v2` cosine similarity routing.
- **Hybrid Workspace Indexer** — Dense vector + BM25 retrieval via Reciprocal Rank Fusion (RRF, k=60).
- **Flash Memory Cache** — Tier-1 in-process ring buffer (100 entries, 307 KB), skips Qdrant on hit.
- `rank-bm25>=0.2.2` added as core dependency.

---

## [3.0.0] — 2026-04-19

### Added
- `LLMAdapter` abstract base class for all provider adapters.
- `LlamaCppAdapter` multi-turn memory via `ConversationContext` injection.
- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md` community health files.

### Fixed
- Qdrant upsert failure: SHA256 → deterministic UUIDv5 point IDs.
- `LlamaCppAdapter` exception mapping corrected.

---

## [2.0.0] — 2026-04-17

### Added
- Clean Architecture rewrite: `src/core/`, `src/app/`, `src/infra/` layers.
- LLM Router with priority-based fallback across LlamaCpp, Groq, Gemini.
- FastAPI REST API with JWT authentication.
- Telegram Bot integration.
- Vector memory with Qdrant for long-term semantic recall.
- Docker + docker-compose.
- GitHub Actions CI/CD pipeline.

---

## [1.0.0] — Legacy

Initial prototype — single-file assistant with basic Gemini integration.

[3.2.2]: https://github.com/adityatawde9699/Amadeus-AI/compare/v3.2.1...v3.2.2
[3.2.1]: https://github.com/adityatawde9699/Amadeus-AI/compare/v3.2.0...v3.2.1
[3.2.0]: https://github.com/adityatawde9699/Amadeus-AI/compare/v3.1.0...v3.2.0
[3.1.0]: https://github.com/adityatawde9699/Amadeus-AI/compare/v3.0.0...v3.1.0
[3.0.0]: https://github.com/adityatawde9699/Amadeus-AI/compare/v2.0.0...v3.0.0
[2.0.0]: https://github.com/adityatawde9699/Amadeus-AI/releases/tag/v2.0.0
