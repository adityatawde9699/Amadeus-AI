# Changelog

All notable changes to Amadeus-AI are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — 2026-11 audit remediation

### Security
- **Breaking:** `/confirm` and `/messaging` now use the fastapi-users auth stack. The custom JWT verifier rejected every login token. HITL confirmations are bound to their owner, `/messaging/send` is admin-only, and the ephemeral `SECRET_KEY` is generated once per process.
- **MCP tools are policy-gated.** They default to STANDARD + confirmation, and only allowlisted tools are read-only. The filesystem server is rooted at the agent workspace and disabled by default.
- **Breaking: tasks are per-user** (`tasks.owner_id`, migration `e1f2a3b4c5d6`). `GET /tasks/summary` is no longer shadowed by `/tasks/{id}`.
- **Health, LLM-usage and metrics endpoints now need auth.** Metrics accept the `METRICS_TOKEN` bearer or a loopback caller only.
- **Proactive checks run READ_ONLY** and deliver their summaries in code.
- **Hardening fixes:**
  - The calculator now resists DoS.
  - `ping` and `grep` are guarded against argument injection.
  - llama.cpp inference is serialised.
  - Argument remapping is limited to read-only tools.
- **SEC-01 is now implemented** (`src/core/prompt_safety.py`):
  - `<user_task>` and `<untrusted_data>` fences, control-token neutralisation and size caps;
  - a taint gate that requires approval for state-changing tools after external content.
  - It had been documented before but was missing from the code.
- **Secret scanning:** gitleaks in pre-commit and CI; CI now runs on `master`.
- **`master` is the only branch:**
  - CI triggers on `master` only.
  - Deploy (prod) runs on pushes to `master` and is skipped while `RAILWAY_TOKEN` is unset.
  - A release is cut once per new `pyproject` version, instead of rewriting an existing release.
  - The Railway action is pinned by commit SHA.
- **Dependency CVEs cleared:**
  - Vulnerable locked packages were upgraded: starlette 1.10, cryptography, pillow, mcp, torch, transformers, urllib3, virtualenv and others.
  - `python-jose` was removed. The slowapi rate-limit key now verifies the JWT instead of trusting unverified claims.
  - pip-audit now covers the whole lockfile.

### Changed
- **Single HTTP client:** `httpx` replaces `aiohttp`. Removed the unused `requests`, `psycopg`, `pytesseract`, `duckduckgo-search` (`ddgs` stays) and `openai` dependencies.
- **Docker router artifacts:** a new build stage produces the ONNX embedder and `Model/category_classifier.npz` with a CPU-only toolchain. The runtime stays torch-free.
- **Docker image cleanup:** the image now ships `config/`, and the stale `WHISPER_*` env vars are gone.
- **`runtime/cognitive` is now an execution journal.** It records one run per request, around the LangGraph graph. It no longer emulates a plan/verify state machine around one hard-coded step. The events are `plan.created`, `plan.step.*` and `plan.completed`/`plan.failed`; `memory.committed` was removed.
- **Removed the dead joblib classifier pipeline** (`scripts/retrain_classifier.py`, `Model/*.joblib`) and its broken CI job. Use `scripts/train_category_classifier.py` instead.
- **Docs corrected:** no Ollama or OpenAI adapters exist, the project is not "production-ready", and there are 70 built-in tools.

### Added
- **Constrained tool selection.** The plan and reflect nodes send a JSON schema (`src/app/services/action_schema.py`):
  - `tool` is limited to the expert's tools plus `FINISH`, and `args` to each tool's real parameter names.
  - llama.cpp compiles the schema into a GBNF grammar, so local output is always a valid action.
  - With a schema present, the router no longer skips the local model for structured calls.
- **Eval harness (`evals/`)** with baselines committed in `evals/results/`:
  - routing classifier: held-out set, cross-validation and confusion matrix;
  - workspace RAG: recall@k and MRR, comparing hybrid, BM25 and dense retrieval;
  - agent tool-selection on the real graph and local model.
  - A CI floor keeps held-out routing accuracy at 80% or higher.
  - Baselines:
    - Routing: 88.7% held-out accuracy (n=62).
    - RAG, hybrid retrieval: R@1 72%, MRR 0.808 (BM25 alone 64% / 0.756, dense alone 60% / 0.750).
    - Agent on Llama-3.2-1B Q4 (22 tasks, first tool plus argument checks):

      | Configuration | Pass rate |
      |---|---|
      | Expert, grammar-constrained | 68% |
      | Expert, free | 55% |
      | Generalist, grammar-constrained | 27% |
      | Generalist, free | 27% |

      Routing to an expert matters more than the grammar, and the 1B model is too weak to pick from all 70 tools.
- **Multi-worker state:**
  - `SHARED_STATE_BACKEND=redis` puts HITL confirmations (`RedisConfirmationCallback`) and the pre-auth rate limit in Redis.
  - `CHECKPOINT_BACKEND=postgres` uses Postgres LangGraph checkpoints (new `[scale]` extra; Docker: `--build-arg UV_SYNC_EXTRAS="--extra scale"`).
  - The defaults are unchanged: in-process state and SQLite.
- **Settings:** `HITL_TIMEOUT_SECONDS` (was hard-coded to 60 s) and `CHECKPOINT_POSTGRES_URL`.

### Fixed
- **Workspace RAG was a silent no-op in a default install and the Docker image.** It required sentence-transformers and now uses the ONNX MiniLM embedder.
- **Semantic routing in the image failed to load.** `tokenizers` arrived only via the `[ml-fallback]` extra and is now a core dependency.
- **Docker image cleanup:** the leftover 90 MB `model_fp32.onnx.data` was removed (image 1.35 GB → 1.06 GB), and the artifact toolchain is pinned.
- **Migrations failed on an empty PostgreSQL database.** `goal_steps` re-created the `scheduledtaskstatusdb` enum. Downgrades now drop their enum types, so `downgrade base` then `upgrade head` round-trips. CI runs that round trip.
- **`get_async_database_url` corrupted an already-async SQLite URL** into `sqlite+aiosqlite+aiosqlite://`. This broke `alembic` on SQLite.
- **MCP server `env` blocks are now passed to the server process.** `${VAR}` is expanded from the daemon environment, and an unset variable is skipped with a warning.
- **The Docker sandbox couldn't read its script when the host uid wasn't 1000**, for example on CI runners.
- **Schema drift reconciled** (migration `f2a3b4c5d6e7`; `alembic check` now fails CI on drift):
  - `scheduled_tasks` gets a migration; it is created only if missing.
  - Older `timestamptz` columns become naive UTC via `AT TIME ZONE 'UTC'`, preserving the stored instants.
  - NULLs are backfilled before NOT NULL is applied.
  - `ix_tasks_status` is added.
  - Duplicate unique constraints are dropped only where a unique index already enforces them.
  - Every step inspects the live schema first, so databases built by `create_all` migrate safely too.
- **Reminders and Pomodoro crashed on PostgreSQL.** asyncpg rejected the timezone-aware `datetime.now(UTC)` values they wrote. A new `UTCDateTime` column type normalises aware values to naive UTC on bind.

- **`QueueManager.get_job_result` always failed.** It called `ArqRedis.get_job`, which doesn't exist. It now uses `arq.jobs.Job`. Found by mypy.
- **"unmute" muted the volume.** The volume argument parser matched `"mute"` first.
- **One-line meta-narration from the model reached the user unchanged.** The response sanitizer returned the original text when stripping the meta prefix emptied it.
- **Docker: the compose `worker` ran `uv run arq …`,** but the runtime image has no `uv`. It now runs `arq` from the venv.
- **Docker: the image had no local LLM.** The GGUF is gitignored and `.dockerignore`d. Compose now sets `SLM_MODEL_REPO_ID`/`SLM_MODEL_FILENAME`/`SLM_MODEL_PATH` and downloads the model on first start into a persistent `gguf` volume. A missing `SLM_MODEL_PATH` now downloads to its own directory instead of `Model/`. Optional `--build-arg GGUF_REPO_ID=… GGUF_FILENAME=…` bakes the model into the image.

### Internal
- **`agent_loop.py` split into mixins** under `src/app/services/agent_graph/` (`state`, `actions`, `outcomes`, `orchestration`, `expert`). It went from about 1,300 lines to about 320.
  - Method bodies are byte-for-byte unchanged (verified via AST comparison).
  - `agent_loop` still exports `AmadeusGraph`, `AgentResult` and `QueueFullError`.
- **mypy is clean and blocking in CI** (93 errors fixed). `platform = "linux"` makes local runs match CI.
- **CI installs CPU-only torch.** `[tool.uv.sources]` points torch at the PyTorch CPU index on Linux/Windows, which removed 45 `nvidia-*` packages and `triton` from the lock.
- **Coverage is up from 47% to 59%** with new tests for the argument extractor, response composer, workspace RAG indexer, Groq and Gemini adapters, the tool registry and GGUF resolution. The CI gate rises from 45% to 57%.
- `evals/agent_eval.py --configs` runs a subset of configurations.

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
