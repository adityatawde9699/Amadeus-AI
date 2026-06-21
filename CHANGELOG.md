# Changelog

All notable changes to Amadeus-AI are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [6.0.0] — 2026-06-21

Security & build hardening release. Implements the four-phase remediation of the
internal security assessment plus a build/supply-chain pass. The guiding
principle is **fail closed**: when a security-relevant precondition is missing or
ambiguous, deny rather than allow. See `plan.md` for the full phased plan.

> ⚠️ **Breaking changes** — existing deployments must review the items below.
> Several previously fail-*open* behaviors now fail *closed* and will reject
> traffic/operations that used to be silently allowed.

### ⚠️ Breaking
- **Telegram now fails closed.** A bot with no valid `MASTER_TELEGRAM_CHAT_ID`
  allowlist rejects *every* sender (previously it processed all messages with
  full privileges). `start_polling()` refuses to start, and production startup
  errors, without a valid allowlist.
- **Code execution is disabled by default.** `SANDBOX_MODE` is now
  `Literal["disabled", "docker"]`, default `disabled`. `execute_python_script`
  returns "unavailable" unless Docker is configured and reachable.
- **In-process `LocalSandboxExecutor` removed entirely** (file deleted). It was
  trivially escapable and falsely advertised as isolated; there is no local
  execution fallback.
- **Public registration no longer accepts `role` / `tenant_id`** on `UserCreate`
  *or* `UserUpdate` (closed a `PATCH /users/me` privilege-escalation path). New
  users default to `GUEST`; role/tenant changes are admin/out-of-band.
- **`ToolExecutor.execute()` defaults to `READ_ONLY`** (was `SYSTEM_FULL`). It now
  takes a `RequestContext`; callers must pass permissions explicitly.
- **`POST /chat/clear` now requires authentication** and is scoped to the
  caller's own session (also fixed a latent crash — it called the service without
  the required `session_id`).
- **Docker Compose no longer publishes datastore ports.** Postgres/Redis/Qdrant
  and Jaeger OTLP are reachable only on the internal network; the API and Jaeger
  UI bind to loopback (`127.0.0.1`). Run host-side admin tools via
  `docker compose exec`.
- **`sentence-transformers` and `scikit-learn` are no longer core dependencies.**
  They moved to the new `[ml-fallback]` extra. The runtime daemon embeds via
  `onnxruntime` and routes via the pre-trained numpy SVM. Install
  `amadeus-ai[ml-fallback]` to (re)train the classifier or use the ST fallback.

### Security
- **Graduated permission profiles** — added `STANDARD` between `READ_ONLY` and
  `SYSTEM_FULL`, with strict rank ordering and a role→profile mapping
  (`guest→READ_ONLY`, `user→STANDARD`, `admin→SYSTEM_FULL`). The API chat route
  maps the authenticated role; anonymous callers get `READ_ONLY`. Telegram
  allowlisted users get `STANDARD`; `SYSTEM_FULL` requires the new
  `TELEGRAM_ELEVATED_CHAT_IDS` allowlist.
- **`min_permission` authorization boundary** — `ToolCapability` gained
  `min_permission` + `explicit`; the policy engine denies tools whose required
  profile outranks the caller. The bypassable command-substring denylist was
  **removed** as an authorization mechanism. `STRICT_TOOL_METADATA` (default off)
  can deny auto-derived metadata after a full audit.
- **Hardened Docker sandbox** — read-only root FS, all capabilities dropped,
  `no-new-privileges`, PID/memory/swap/CPU caps, networking disabled, non-root
  user, small writable `tmpfs`, pinned image, and an enforced kill timeout.
- **SSRF egress guard** (`net_guard.py`) for `fetch_webpage_content` — rejects
  non-public addresses (loopback, RFC1918, link-local incl. cloud metadata
  `169.254.169.254`, multicast, reserved, IPv4-mapped IPv6), validates every
  redirect hop, caps the body at 2 MiB, and resolves DNS off the event loop with
  a fail-closed timeout. Dev-only escape hatch `ALLOW_PRIVATE_NETWORK_FETCH`
  (forced off in production).
- **Plugin management locked down** — `manage_plugins` is admin-only
  (`min_permission=system_full`) + confirmation-gated, containment-checks the
  plugin name (no traversal), and no longer imports/executes freshly written code
  in the same request (loads on restart).
- **Filesystem path containment** — `_safe_resolve` uses `Path.is_relative_to`
  instead of a bypassable string-prefix check.
- **Request-scoped, owner-aware confirmations** — per-session callback registry
  on `ToolExecutor` removes the global-singleton race; the Telegram callback
  handler verifies the click originates from the owning chat.
- **Per-IP pre-auth rate limiting** (`RateLimitMiddleware`) on
  login/register/forgot/reset/verify, with bounded memory (stale-IP eviction +
  hard cap). Configurable via `RATE_LIMIT_*` / `TRUST_PROXY_HEADERS`.
- **Stopped logging password-reset / verification tokens** (DEBUG-only in dev).
- **Least-privilege background work** — scheduler, watchers, autonomous loop,
  goal executor, and container background dispatch run at `STANDARD`, not
  `SYSTEM_FULL`.

### Build & Supply Chain
- **Reproducible image** — the Dockerfile installs with `uv sync --frozen` (exact
  `uv.lock` versions CI/`pip-audit` vet) instead of `pip install .`, which
  re-resolved `>=` ranges at build time.
- **Leaner runtime image** — the torch/transformers/scipy/sklearn stack is no
  longer installed in the runtime image (moved to `[ml-fallback]`), keeping the
  daemon within the 4 GB / <300 MB RSS budget (CLAUDE.md §3).
- `.dockerignore` now blocks `.env` / `.env.*` (keeps `!.env.example`); the dead
  `model_cache` build stage was collapsed.

### Fixed
- `RateLimitMiddleware` unbounded per-IP table (memory leak) — now evicted.
- SSRF guard performed blocking DNS on the event loop — now off-loop with timeout.
- `clear_conversation` invoked without its required `session_id`.

### Tests
- New `tests/unit/test_security_phase1_2.py`, `test_security_phase3_4.py`, and
  `test_build_hardening.py` (allowlist parsing, registration lockdown, fail-closed
  sandbox, profile/min-permission enforcement, owner-scoped confirmations, SSRF,
  plugin/path containment, token-log suppression, rate-limit eviction/reset,
  reproducible-build asserts, no-torch-at-runtime guard).

### Known Issues
- `uv.lock` carries a yanked transitive `grpcio==1.78.1` (via the OTLP exporter);
  `pip-audit`/CI may flag it. A pin/upgrade is a follow-up change.
- The SSRF guard retains a small validate-then-connect TOCTOU/DNS-rebind window;
  full closure requires pinning the validated IP into the connection.

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

[6.0.0]: https://github.com/adityatawde9699/Amadeus-AI/compare/v5.0.0...v6.0.0
[5.0.0]: https://github.com/adityatawde9699/Amadeus-AI/compare/v4.0.0...v5.0.0
[3.2.2]: https://github.com/adityatawde9699/Amadeus-AI/compare/v3.2.1...v3.2.2
[3.2.1]: https://github.com/adityatawde9699/Amadeus-AI/compare/v3.2.0...v3.2.1
[3.2.0]: https://github.com/adityatawde9699/Amadeus-AI/compare/v3.1.0...v3.2.0
[3.1.0]: https://github.com/adityatawde9699/Amadeus-AI/compare/v3.0.0...v3.1.0
[3.0.0]: https://github.com/adityatawde9699/Amadeus-AI/compare/v2.0.0...v3.0.0
[2.0.0]: https://github.com/adityatawde9699/Amadeus-AI/releases/tag/v2.0.0
