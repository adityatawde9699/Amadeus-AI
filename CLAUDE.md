# CLAUDE.md — Amadeus AI v5.0.0

> Project context for Claude Code. Read this before touching any file.

---

## Project Overview

**Amadeus** is a locally-running autonomous AI assistant daemon built with Python 3.11+.

- **Primary interface**: Telegram (long-polling via `python-telegram-bot`)
- **Secondary interface**: FastAPI REST API (internal, loopback-only by default)
- **Architecture**: Clean Architecture — core → app → infra → transports
- **Agent engine**: LangGraph `StateGraph` (replaced legacy ReAct loop in v5)
- **Local LLM**: `llama-cpp-python` (GGUF models via `LlamaCppAdapter`)
- **Memory**: Turbovec in-process vector store (4-bit quantized, primary) + optional Qdrant archival
- **Tool protocol**: MCP (Model Context Protocol) + custom Python tool registry
- **DI framework**: `dependency-injector` — all singletons wired in `src/container.py`

---

## Repository Layout

```
Amadeus-AI/
├── src/
│   ├── api/              # FastAPI route handlers + auth + middleware
│   │   ├── auth/         # fastapi-users auth backend, JWT, RBAC
│   │   ├── middleware/   # AuditLogger, Tracing, Authentication, RBAC
│   │   └── routes/       # chat, confirm, health, llm, messaging, readiness, tasks, webhooks
│   ├── app/
│   │   └── services/     # Business logic layer
│   │       ├── agent_loop.py          # AmadeusGraph (LangGraph StateGraph) — PRIMARY AGENT
│   │       ├── amadeus_service.py     # Main orchestrator (thin, delegates to sub-services)
│   │       ├── argument_extractor.py  # NLP → tool argument dicts
│   │       ├── autonomous_loop.py     # Background proactive observation loop
│   │       ├── category_classifier.py # SVM-based tool category classifier
│   │       ├── conversation_manager.py
│   │       ├── messaging_service.py
│   │       ├── proactive_service.py
│   │       ├── response_composer.py   # LLM prose generation + system prompts
│   │       ├── semantic_router.py     # UnifiedSemanticRouter (embedding-based triage)
│   │       ├── tool_dispatcher.py     # Tool lookup, execution, timeouts, cache
│   │       └── tool_registry.py       # Tool registration + MCP client
│   ├── core/
│   │   ├── config.py      # Pydantic Settings (lru_cache singleton)
│   │   ├── domain/        # Domain models + RequestContext
│   │   ├── exceptions.py
│   │   └── interfaces/    # Repository ABCs
│   ├── infra/
│   │   ├── cache/         # CacheService (Redis + in-memory fallback)
│   │   ├── llm/           # LLM adapters: llama_cpp, gemini, groq + LLMRouter
│   │   ├── memory_service.py
│   │   ├── messaging/     # EmailAdapter
│   │   ├── metrics.py     # Prometheus counters
│   │   ├── model_manager.py  # GGUF auto-download
│   │   ├── persistence/   # SQLAlchemy ORM, Alembic, repositories
│   │   ├── queue/         # ARQ task queue + Redis
│   │   ├── resilience/    # CircuitBreaker, Watchdog
│   │   ├── sandbox/       # Docker/local Python sandbox
│   │   ├── search/        # SearchRouter (DDG + Tavily)
│   │   ├── system/        # System info helpers
│   │   ├── tools/         # All tool implementations (17 files)
│   │   ├── turbovec_memory.py  # Turbovec vector memory service
│   │   └── workspace_indexer.py
│   ├── runtime/
│   │   ├── cognitive/     # CognitiveCore + models
│   │   ├── core.py        # AmadeusRuntime (start/stop lifecycle)
│   │   ├── events.py
│   │   └── scheduler.py
│   ├── transports/
│   │   ├── cli_transport.py      # Minimal CLI (single-shot, not the main interface)
│   │   ├── fastapi_transport.py  # Main entry point — lifespan, middleware, routes
│   │   └── telegram_transport.py # Telegram handler wired into FastAPI lifespan
│   └── container.py  # Dependency-injector IoC container (SINGLE SOURCE OF TRUTH for DI)
├── config/
│   ├── agents.yaml       # LangGraph agent personas + tool categories
│   └── mcp_servers.yaml  # MCP server definitions
├── tests/
│   ├── unit/             # 19 unit test files
│   └── integration/      # DB, sandbox, LLM routing tests
├── alembic/              # DB migrations
├── deploy/
│   └── amadeus.service   # systemd unit file
├── plugins/              # Drop-in tool plugins (auto-discovered)
├── Model/                # Local GGUF models (gitignored)
├── data/                 # Runtime data: logs, vector_db, sqlite checkpoints
├── pyproject.toml        # uv/hatch build config + ruff/mypy/pytest config
└── .env                  # Local secrets (never commit)
```

---

## Key Architectural Rules

### 1. Dependency Injection
- **All singletons** live in `src/container.py` (`global_container`).
- Never instantiate `AmadeusService`, `LLMRouter`, `ToolRegistry`, `CacheService` directly in route handlers — use DI providers.
- Route handlers get dependencies via `dependency-injector` `@inject` + `Provide[Container.xxx]`.

### 2. Agent Loop (LangGraph)
- The primary multi-step agent is `AmadeusGraph` in `src/app/services/agent_loop.py`.
- Graph nodes: `plan_node` → `tool_node` → `reflect_node` → `synthesize_node`.
- State schema: `AmadeusState` (TypedDict with list reducers).
- Checkpointer: `SqliteSaver` persisted to `data/langgraph_checkpoints.sqlite`.
- Single-step queries bypass the graph and go through `_process_command_internal()`.

### 3. Request Context
- Every call to `handle_command()` and tool execution must carry a `RequestContext` (from `src/core/domain/context.py`).
- `RequestContext` carries: `request_id`, `session_id`, `user_id`, `permissions`, `memory_scope`, `trace_id`, `cancellation_token`.
- Never pass raw user IDs or session strings where `RequestContext` is expected.

### 4. LLM Routing
- `LLMRouter` in `src/infra/llm/router.py` routes between: `LlamaCppAdapter` (local, priority) → `GroqAdapter` (free tier) → `GeminiAdapter` (cloud fallback).
- `LOCAL_ONLY_MODE=True` (default) blocks all cloud adapters.
- When adding new LLM calls, always go through `LLMRouter.generate()`, never call adapters directly.

### 5. Tool System
- Tools are registered in `ToolRegistry` via `registry.register(tool)`.
- Tool implementations live in `src/infra/tools/`.
- New tools must extend the base tool pattern in `src/infra/tools/base.py`.
- MCP servers are configured in `config/mcp_servers.yaml` and connected at startup.
- Drop-in plugins go in `plugins/` and are auto-discovered.

### 6. Memory
- Primary: `TurbovecMemoryService` (`src/infra/turbovec_memory.py`) — in-process, 4-bit quantized.
- Secondary/archival: Qdrant (optional extra: `pip install "amadeus-ai[archival_memory]"`).
- Always call `memory_service.store()` after significant interactions.

### 7. Transport Layer
- **Telegram is the primary interface.** Long-polling is started in the FastAPI lifespan.
- `fastapi_transport.py` is the main entry point (`uvicorn src.transports.fastapi_transport:app`).
- `cli_transport.py` is a debug utility, not a supported interface.
- The FastAPI API is internal (loopback `127.0.0.1:8765` by default).

---

## Development Commands

```bash
# Install deps (uv recommended)
uv sync --extra dev

# Run server (primary entry point)
uvicorn src.transports.fastapi_transport:app --host 127.0.0.1 --port 8765 --reload

# Run tests
uv run pytest tests/ -v

# Run unit tests only
uv run pytest tests/unit/ -v

# Lint + format
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Type check
uv run mypy src/

# Database migrations
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"

# Security scan
uv run bandit -r src/ -ll
```

---

## Environment Variables (Critical)

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | **Yes** | Bot token from @BotFather |
| `DATABASE_URL` | Yes | PostgreSQL or SQLite URL |
| `SECRET_KEY` | Prod only | JWT signing key (32-byte hex) |
| `LOCAL_ONLY_MODE` | No | `True` = block all cloud LLMs (default: `True`) |
| `SLM_MODEL_PATH` | No | Absolute path to `.gguf` model file |
| `GEMINI_API_KEY` | No | Google Gemini (cloud fallback) |
| `GROQ_API_KEY` | No | Groq free-tier LLM |
| `REDIS_URL` | No | Redis for cache + rate limiting (default: `redis://localhost:6379/0`) |
| `MASTER_TELEGRAM_CHAT_ID` | No | Chat ID for proactive notifications |

See `.env.example` for the full list.

---

## Testing

```bash
# Baseline: ~118 passed, 45 failed (pre-existing LLM adapter + Telegram drift failures)
uv run pytest tests/ -q

# Coverage
uv run pytest tests/ --cov=src --cov-report=term-missing

# Skip slow tests
uv run pytest tests/ -m "not slow"
```

**Known pre-existing failures**: Tests in `test_llama_cpp_adapter.py`, `test_llm_router.py`, and Telegram message flow tests fail because they require live model files or a running Telegram bot. These are not regressions.

---

## Code Style

- **Formatter**: `ruff format` (line length 100)
- **Linter**: `ruff check` with a broad rule set (see `pyproject.toml [tool.ruff.lint]`)
- **Type checker**: `mypy --strict` (some overrides in `pyproject.toml`)
- **Python**: 3.11+ features allowed (`match`, `|` union types, etc.)
- **Imports**: isort via ruff (`known-first-party = ["src"]`)
- All public functions must have type annotations.
- Use `structlog` for logging in transport layer; `logging.getLogger(__name__)` elsewhere.

### Ignored rules (intentional)
- `B008` — `Depends()` in default args (FastAPI DI pattern)
- `S307` — `eval()` in controlled tool sandbox
- `ERA001` — commented-out code (too many false positives)
- `E501` — line-too-long (tool descriptions and URLs)

---

## Security Constraints

- **Never** use `shell=True` in subprocess calls — use array form.
- **Never** log secrets, API keys, or full user messages at INFO level.
- **Never** expose stack traces to API clients in production (`ALLOW_DEBUG_RESPONSES=False`).
- Tool execution goes through `ToolPolicyEngine` and `CircuitBreaker` — do not bypass.
- HITL (human-in-the-loop) confirmation is required for destructive tools — use `APIConfirmationCallback`.
- All file operations must stay within `AGENT_WORKSPACE` (sandboxed path).
- `SECRET_KEY` must be set in production; an ephemeral key is auto-generated in dev (invalidates JWTs on restart).

---

## Adding a New Tool

1. Create implementation in `src/infra/tools/<category>_tools.py`
2. Return a list of `Tool` objects from a `get_<category>_tools()` or `build_<category>_tools()` factory
3. Register in `src/container.py` inside `_build_tool_registry()`
4. Add tool category to `config/agents.yaml` if it belongs to a specialized agent
5. Write unit tests in `tests/unit/`

## Adding a New API Route

1. Create handler in `src/api/routes/<name>.py`
2. Register router in `src/transports/fastapi_transport.py`
3. Add module to `Container.wiring_config.modules` in `src/container.py`
4. Add auth dependency (`protected_deps`) unless the route is public (health/readiness)

---

## Common Gotchas

- `get_settings()` is `lru_cache`-d — changes to `.env` after first call are ignored. Restart the server.
- `AmadeusService` is a singleton — it is **not** safe to store per-request state on it.
- The `SqliteSaver` checkpointer uses a synchronous `sqlite3` connection (`check_same_thread=False`) — do not use it from multiple threads.
- Alembic migrations are run automatically at startup via `subprocess` (to avoid asyncio deadlock with `asyncio.run()` inside uvicorn's loop).
- `LlamaCppAdapter` loads the full GGUF model into RAM at init — expect 2–8 GB RAM usage depending on the model.
- Turbovec requires the embedding model to be warmed up before first query (`await memory_service.initialize()`).
- The `AutonomousObservationLoop` runs every 60 minutes and posts to `MASTER_TELEGRAM_CHAT_ID` — set `PROACTIVE_DRY_RUN=True` during development.
