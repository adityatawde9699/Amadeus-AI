# Amadeus AI — v5.0.0 Implementation Plan

**Codebase baseline:** v3.2.0 / v4.0.0 (README)  
**Target release:** v5.0.0  
**Status:** Pre-implementation design  
**Author:** Aditya S. Tawde

---

## Executive Summary

Amadeus is already a production-grade autonomous AI operating layer with Clean Architecture, a two-stage semantic router, multi-LLM routing with circuit breakers, Qdrant episodic memory, HITL confirmation gates, and a CognitiveCore state machine. v5.0.0 is not a rewrite — it is a **targeted capability upgrade** across six engineering pillars that close the gap between the current single-process architecture and a true multi-agent, daemon-grade, locally-sovereign AI platform.

The two biggest architectural decisions this plan resolves:

- **Orchestration:** Replace the custom `ReActAgent` + `AgentOrchestrator` with **LangGraph** (not CrewAI). The existing CognitiveCore state machine, HITL pause/resume flow, and circuit-breaker-wired event bus all map directly onto LangGraph's graph-node-checkpoint model. CrewAI's "team collaboration" model would require abandoning these investments for marginal gain.
- **Vector memory:** Replace Qdrant with **Turbovec** (`turbovec.IdMapIndex`) for the primary in-process embedding store. Qdrant stays as an optional remote tier for archival memory.

---

## Pillars at a Glance

| # | Pillar | Core Change | Risk |
|---|--------|-------------|------|
| 1 | Multi-Agent Orchestration | ReActAgent → LangGraph state graph | Medium |
| 2 | Deep RAG Memory | Qdrant → Turbovec (local) + Qdrant (archival) | Low |
| 3 | MCP Tool Registry | Custom `plugins/` → MCP client in `ToolRegistry` | Medium |
| 4 | Multimodal Vision | VLM adapter (LLaVA / Gemini Flash) + screen capture | Low |
| 5 | Web Dashboard | Next.js App Router mission control frontend | Low |
| 6 | 24/7 Daemon Hardening | systemd service, structured shutdown, memory pruning | Low |

---

## Phase 0 — Pre-Work & Audit Closure (Week 0–1)

Before any feature work, close the six critical security issues from the prior engineering audit. These are blockers for multi-user safety.

### 0.1 Harden Security Gaps

| Item | File | Action |
|------|------|--------|
| Hardcoded credentials | `.env.example`, `docker-compose.yml` | Rotate and remove all plaintext secrets; verify `SECRET_KEY` is always set in prod |
| Unauthenticated WebSocket | `src/transports/fastapi_transport.py` | Move JWT check to the `101 Upgrade` handshake in `WS /api/v1/ws/voice` |
| Shell injection vector | Legacy tool call sites | Audit all `subprocess` calls; confirm zero `shell=True` paths remain |
| Unbounded `ConversationManager` dict | `src/app/services/conversation_manager.py` | The dict is already bounded by `max_context=20`; confirm no unbounded session map elsewhere in `AmadeusService` |
| `ALLOW_DEBUG_RESPONSES` in prod | `src/core/config.py` | Enforce `ALLOW_DEBUG_RESPONSES=False` via `validate_settings()` when `ENV=production` |
| `shell=True` subprocess in developer tools | `src/infra/tools/developer_tools.py` | `terminal_cmd` already uses `shlex.split` + `shell=False`; audit remaining `subprocess.Popen` calls in `system_tools.py` |

### 0.2 Test Baseline

```bash
uv run pytest tests/ -v --cov=src --cov-report=term-missing
```

Record baseline coverage percentage. v5.0.0 must not drop below it.

---

## Phase 1 — LangGraph Multi-Agent Orchestration (Weeks 2–4)

### 1.1 Rationale

The current `ReActAgent` + `AgentOrchestrator` (in `src/app/services/agent_loop.py`) implement a custom async state machine that already mirrors LangGraph semantics: state transitions, an explicit `AgentState` enum, a scratchpad, and a cycle-detection guard. LangGraph replaces this with a graph-persistent, checkpoint-capable equivalent that natively supports:

- HITL pause at any edge via `interrupt_before`
- Serialized state recovery after crashes or restarts
- Per-node streaming for real-time frontend dashboards
- TypedDict state schema enforced at graph compile time

CrewAI is explicitly **not chosen** because Amadeus's existing `ConfirmationCallback`, `ToolPolicyEngine`, and `CircuitBreaker` infrastructure already implement enterprise-grade safety and resilience. Wrapping that inside CrewAI's execution model would either duplicate or bypass it.

### 1.2 Files Modified

#### `src/app/services/agent_loop.py`

- **Deprecate:** `ReActAgent`, `AgentOrchestrator`, `AgentState`, `AgentStep` classes.
- **Add:** `AmadeusGraph` — a LangGraph `StateGraph` compiled to a `CompiledGraph`.
- **State schema:**

```python
from typing import Annotated
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

class AmadeusState(TypedDict):
    messages: Annotated[list, add_messages]
    task: str
    plan: str
    observations: list[str]
    tools_used: list[str]
    final_answer: str
    requires_hitl: bool
    hitl_request_id: str
    permission_profile: str
    session_id: str
    iteration: int
```

- **Nodes:**
  - `plan_node` — calls LLM to decompose task into steps
  - `tool_node` — executes tools via the existing `ToolDispatcher`
  - `reflect_node` — post-tool observation, updates state
  - `synthesize_node` — composes final answer
  - `hitl_node` — serializes state, fires `ConfirmationCallback`, awaits resolution
- **Edges:**
  - `plan_node → tool_node`
  - `tool_node → hitl_node` (if `requires_hitl=True`)
  - `tool_node → reflect_node` (otherwise)
  - `reflect_node → tool_node` (loop back) or `reflect_node → synthesize_node` (done)
  - `hitl_node → tool_node` (approved) or `hitl_node → synthesize_node` (denied)

#### `src/app/services/amadeus_service.py`

- Replace `self.orchestrator = AgentOrchestrator(...)` with `self.graph = AmadeusGraph(...)`.
- `_process_with_agent()` becomes `await self.graph.ainvoke(state)`.
- Pass `RequestContext` through graph state so all nodes are context-aware.

#### `config/agents.yaml` *(new)*

Externalize agent persona definitions, max-iteration caps, and tool-access scopes. Parsed at startup and injected into `AmadeusGraph`.

```yaml
agents:
  system_operator:
    description: "Handles filesystem, OS commands, and sandbox execution."
    max_iterations: 3
    tool_categories: [app_control, file_system, os_control]

  researcher:
    description: "Handles web search, document retrieval, and RAG queries."
    max_iterations: 5
    tool_categories: [web_research, weather]

  communicator:
    description: "Handles email, Telegram, and notification drafting."
    max_iterations: 3
    tool_categories: [communication]
```

#### `config/tasks.yaml` *(new)*

Task templates that map user intent categories to recommended agent routing.

### 1.3 LangGraph Checkpointing

```python
from langgraph.checkpoint.aiosqlite import AsyncSqliteSaver

checkpointer = AsyncSqliteSaver.from_conn_string(
    str(settings.DATA_DIR / "graph_checkpoints.db")
)
graph = graph_builder.compile(checkpointer=checkpointer)
```

This gives every in-flight task full crash recovery. A restarted daemon can resume from `thread_id = session_id`.

### 1.4 HITL Integration

The `hitl_node` calls the existing `APIConfirmationCallback.request_approval()` and suspends. No new infrastructure — LangGraph's `interrupt_before` mechanism replaces the ad-hoc `asyncio.Future` in the current `TelegramConfirmationCallback`.

### 1.5 Verification

```
pytest tests/unit/test_agent_loop.py -v
```

Manual: send "Check my emails and summarize them, then search the web for related news." — verify LangGraph routes to `communicator` then `researcher`, not a single ReAct loop.

---

## Phase 2 — Turbovec Deep RAG Memory (Weeks 3–5)

### 2.1 Rationale

The current `QdrantMemoryService` runs as an `AsyncQdrantClient` against a local file-based Qdrant instance. For single-machine personal use, this is over-engineered: Qdrant's persistence model (WAL + HNSW index rebuild) adds latency on cold starts and holds a file lock that causes problems during rapid restarts. Turbovec's `IdMapIndex` operates entirely in process memory, saves to a single `.tq` file, and achieves 16× compression via TurboQuant 2-bit quantization — keeping Amadeus's full memory footprint under 500 MB even at 10 million stored interactions.

Qdrant is retained as an **optional archival tier** for workspaces that need cross-device sync or ACID guarantees.

### 2.2 Files Modified

#### `src/infra/memory_service.py`

- **Add:** `TurbovecMemoryService` class implementing the same `store()` / `retrieve()` / `clear_session()` / `format_for_prompt()` interface as `QdrantMemoryService`.
- **Key implementation:**

```python
import turbovec

class TurbovecMemoryService:
    def __init__(self, settings: Settings) -> None:
        self._index: turbovec.IdMapIndex | None = None
        self._index_path = Path(settings.DATA_DIR) / "turbovec_memory.tq"
        self._metadata: dict[str, dict] = {}  # id → payload
        self._embed_model: SentenceTransformer | None = None
        self._enabled = settings.MEMORY_ENABLED

    async def initialize(self) -> None:
        self._embed_model = SentenceTransformer(settings.EMBED_MODEL_NAME)
        dim = self._embed_model.get_sentence_embedding_dimension()
        self._index = turbovec.IdMapIndex(dim=dim, bits=4)  # 4-bit: balance recall vs size
        if self._index_path.exists():
            self._index.read(str(self._index_path))

    async def store(self, session_id, role, text, **kwargs) -> bool:
        vec = self._embed_model.encode(text, normalize_embeddings=True)
        uid = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{session_id}:{role}:{text}"))
        self._index.add(uid, vec)
        self._metadata[uid] = {"session_id": session_id, "role": role, "text": text, ...}
        self._index.write(str(self._index_path))
        return True

    async def retrieve(self, query, top_k=5) -> list[MemoryResult]:
        q_vec = self._embed_model.encode(query, normalize_embeddings=True)
        results = self._index.search(q_vec, k=top_k * 2)
        # Post-filter by similarity threshold, apply recency decay, return top_k
        ...
```

- **Retain:** `QdrantMemoryService` as `QdrantArchivalMemoryService` for optional remote/cloud tier.
- **Tiered routing:** `retrieve()` checks Turbovec first; if result count is below threshold, also queries Qdrant archival tier and merges.

#### `src/core/config.py`

- **Remove:** `QDRANT_URL`, `MEMORY_PERSIST_DIR` (Qdrant-specific).
- **Add:**

```python
TURBOVEC_INDEX_PATH: str = "./data/turbovec_memory.tq"
TURBOVEC_BITS: int = 4          # 2 | 4 | 8 — quantization bit-width
QDRANT_ARCHIVAL_ENABLED: bool = False
QDRANT_URL: str | None = None   # kept optional for archival tier
```

#### `src/container.py`

- Replace `QdrantMemoryService` singleton with `TurbovecMemoryService`.
- Add optional `QdrantArchivalMemoryService` behind `QDRANT_ARCHIVAL_ENABLED` flag.

### 2.3 Allowlist Filtering

Turbovec's hardware-level `allowlist` parameter enables zero-penalty pre-filtered search. This replaces the current expensive post-filter loop:

```python
# SQL query to get session-scoped IDs
session_ids = await db.scalars(
    select(MessageORM.id).where(MessageORM.session_id == session_id)
)
results = self._index.search(q_vec, k=top_k, allowlist=list(session_ids))
```

### 2.4 Verification

```
pytest tests/unit/test_turbovec_memory.py -v
```

Test cases: store 1000 vectors, retrieve with cosine similarity threshold, verify 4-bit vs 8-bit recall delta is within 2%.

---

## Phase 3 — MCP Tool Registry (Weeks 5–7)

### 3.1 Rationale

Amadeus currently has 70+ hand-written tools in `src/infra/tools/`. Each new integration requires Python glue code. MCP standardizes this — any MCP server (GitHub, PostgreSQL, Filesystem, Jira, Slack) exposes its capabilities in a schema Amadeus can consume without bespoke adapters.

### 3.2 Files Modified

#### `src/app/services/tool_registry.py`

- **Add:** `connect_mcp_server(url: str, name: str)` method.
- **Implementation:**

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def connect_mcp_server(self, url: str, name: str) -> int:
    """Connect an MCP server and register its tools. Returns count registered."""
    async with stdio_client(StdioServerParameters(command=url)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            count = 0
            for mcp_tool in tools_result.tools:
                self._register_mcp_tool(session, mcp_tool, server_name=name)
                count += 1
            return count

def _register_mcp_tool(self, session, mcp_tool, server_name: str) -> None:
    async def _caller(**kwargs):
        return await session.call_tool(mcp_tool.name, kwargs)

    self.register_function(
        func=_caller,
        name=f"{server_name}.{mcp_tool.name}",
        description=mcp_tool.description or "",
        category=ToolCategory.WEB_RESEARCH,
        parameters=mcp_tool.inputSchema or {},
    )
```

#### `config/mcp_servers.yaml` *(new)*

```yaml
mcp_servers:
  - name: filesystem
    command: "npx @modelcontextprotocol/server-filesystem /home/user"
    enabled: true
  - name: github
    command: "npx @modelcontextprotocol/server-github"
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"
    enabled: false
  - name: postgres
    command: "npx @modelcontextprotocol/server-postgres"
    env:
      DATABASE_URL: "${DATABASE_URL}"
    enabled: false
```

#### `src/transports/fastapi_transport.py`

Add MCP server initialization to `lifespan()`:

```python
from src.app.services.tool_registry import get_tool_registry

registry = get_tool_registry()
mcp_config = yaml.safe_load((settings.BASE_DIR / "config/mcp_servers.yaml").read_text())
for server in mcp_config.get("mcp_servers", []):
    if server.get("enabled"):
        await registry.connect_mcp_server(server["command"], server["name"])
```

### 3.3 Verification

Manual: enable `filesystem` MCP server, ask "list files in my home directory" — verify MCP tool is invoked, not the built-in `fs_list_directory`.

---

## Phase 4 — Multimodal Vision (Weeks 6–8)

### 4.1 Files Modified

#### `src/infra/llm/` — new `vlm_adapter.py`

```python
class VLMAdapter:
    """Vision Language Model adapter. Supports local LLaVA via llama-cpp and Gemini Flash."""

    async def describe_image(self, image_bytes: bytes, prompt: str = "Describe this image.") -> str: ...
    async def describe_screen(self, prompt: str) -> str: ...  # captures + describes in one call
```

#### `src/infra/tools/vision_tools.py` *(new)*

```python
@tool(name="describe_screen", ...)
async def describe_screen(query: str) -> str:
    """Capture and describe the current screen to answer a visual question."""
    screenshot = PIL.ImageGrab.grab()
    buf = io.BytesIO()
    screenshot.save(buf, format="PNG")
    adapter = VLMAdapter(settings)
    return await adapter.describe_image(buf.getvalue(), prompt=query)

@tool(name="describe_image_file", ...)
async def describe_image_file(file_path: str, query: str = "Describe this image.") -> str:
    """Describe an image file at the given path."""
    ...
```

#### `src/core/config.py`

```python
VLM_PROVIDER: Literal["local_llava", "gemini_flash", "none"] = "none"
VLM_MODEL_PATH: str | None = None  # path to LLaVA GGUF
```

### 4.2 Verification

Manual: Ask "What application is open on my screen right now?" — verify `describe_screen` tool is triggered and returns an accurate description.

---

## Phase 5 — Web Dashboard (Weeks 7–10)

### 5.1 Architecture

A Next.js 14 App Router frontend connecting to the existing FastAPI backend via:

- REST API for chat, tasks, and tool management
- SSE (`/api/v1/chat/stream`) for real-time streaming responses
- WebSocket (`/api/v1/ws/voice`) for voice sessions
- New: `/api/v1/graph/stream` — SSE endpoint streaming LangGraph node transitions for live execution visualization

### 5.2 Frontend Directory Structure

```
dashboard/
├── app/
│   ├── layout.tsx
│   ├── page.tsx               # Chat interface
│   ├── tasks/page.tsx
│   ├── memory/page.tsx        # Episodic memory browser
│   ├── tools/page.tsx         # Plugin/MCP management
│   └── system/page.tsx        # Resource metrics + alerts
├── components/
│   ├── ChatWindow.tsx          # SSE streaming chat
│   ├── ExecutionGraph.tsx      # LangGraph node visualization (react-flow)
│   ├── ConfirmationModal.tsx   # HITL approve/deny UI
│   ├── SystemMetrics.tsx       # CPU/RAM/disk gauges
│   └── ToolPanel.tsx
└── lib/
    ├── api.ts
    └── sse.ts
```

### 5.3 New Backend Endpoint

#### `src/api/routes/graph.py` *(new)*

```python
@router.get("/graph/stream")
async def stream_graph_events(session_id: str) -> StreamingResponse:
    """SSE stream of LangGraph node transitions for the given session."""
    async def event_generator():
        async for event in graph.astream_events(config={"configurable": {"thread_id": session_id}}):
            yield f"data: {json.dumps(event)}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### 5.4 Tauri Desktop Wrapper (Optional)

For offline/local-first deployments, the Next.js app can be wrapped in Tauri 2.0 to produce a native desktop binary with no browser required. The FastAPI backend continues running as a subprocess managed by the Tauri sidecar API.

### 5.5 Verification

Manual: Start the dashboard, send a multi-step query, watch the LangGraph execution graph animate in real time. Click "Deny" on a HITL modal and verify the tool is aborted.

---

## Phase 6 — 24/7 Daemon Hardening (Weeks 8–10)

### 6.1 Files Modified

#### `deploy/amadeus.service` *(already exists — update)*

```ini
[Unit]
Description=Amadeus AI Autonomous Agent Daemon
After=network.target postgresql.service redis.service
Wants=postgresql.service redis.service

[Service]
Type=simple
User=amadeus
Group=amadeus
WorkingDirectory=/opt/amadeus
EnvironmentFile=/opt/amadeus/.env
ExecStart=/opt/amadeus/.venv/bin/python -m uvicorn src.transports.fastapi_transport:app \
    --host 127.0.0.1 --port 8765 --workers 1 --log-level info
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=10
RestartBurstSec=60
MemoryMax=2G
CPUQuota=80%
StandardOutput=journal
StandardError=journal
SyslogIdentifier=amadeus

[Install]
WantedBy=multi-user.target
```

#### `src/app/services/proactive_service.py`

- Add **context-pruning job**: summarize conversations older than 24 hours into condensed core beliefs via `TurbovecMemoryService.store(..., subtype="summary")`.
- Add **stale-memory pruning**: call `TurbovecMemoryService.prune_stale_memories(session_id, older_than_days=90)` weekly.

#### `src/runtime/core.py`

- Add `graceful_shutdown_timeout: int = 30` — the runtime waits up to 30 seconds for in-flight LangGraph tasks to complete before force-cancelling them.

#### `src/transports/fastapi_transport.py`

- Add `SIGTERM` handler that triggers `runtime.stop()` before uvicorn exits.

### 6.2 Verification

```bash
sudo systemctl start amadeus
sudo journalctl -u amadeus -f
# Verify: no memory leaks after 1 hour of operation
```

Chaos test: `sudo kill -9 $(pidof uvicorn)` — verify systemd restarts within `RestartSec=10`, LangGraph resumes from checkpoint.

---

## Dependency Changes

### `pyproject.toml` additions

```toml
# Phase 1 — LangGraph
"langgraph>=0.2.0",
"langgraph-checkpoint-aiosqlite>=0.0.1",

# Phase 2 — Turbovec
"turbovec>=0.1.0",

# Phase 3 — MCP
"mcp>=1.0.0",

# Phase 4 — Vision
"Pillow>=10.0.0",   # already present

# Phase 5 — Dashboard backend
"sse-starlette>=1.6.0",
"react-flow-py",    # if generating graph layouts server-side
```

### Removals

```toml
# Qdrant moves to optional dependency, not a core requirement
# Remove from default dependencies:
"qdrant-client>=1.7.0"
```

Add as optional:

```toml
[project.optional-dependencies]
archival_memory = ["qdrant-client>=1.7.0"]
```

---

## Testing Strategy

### Unit Tests (per phase)

| Phase | Test File | Focus |
|-------|-----------|-------|
| 1 | `tests/unit/test_langgraph_agent.py` | State transitions, HITL node pause/resume, cycle detection |
| 2 | `tests/unit/test_turbovec_memory.py` | Store/retrieve accuracy, allowlist filtering, persistence |
| 3 | `tests/unit/test_mcp_registry.py` | Tool registration from MCP schema, deduplication |
| 4 | `tests/unit/test_vlm_adapter.py` | VLM routing, fallback handling |
| 5 | `tests/integration/test_graph_stream.py` | SSE event stream format for LangGraph transitions |
| 6 | `tests/integration/test_daemon_recovery.py` | Crash recovery via checkpoint |

### Manual Verification Checklist

- [ ] Multi-agent routing: "Research the latest AI news, summarize it, and save it to a file" — verify three distinct LangGraph nodes activate
- [ ] HITL: "Delete all .log files in Downloads" — verify HITL modal appears, denial aborts execution, approval proceeds
- [ ] Memory: Ask "What did I ask you about yesterday?" — verify Turbovec retrieval returns relevant results
- [ ] MCP: Ask "Show me my open GitHub issues" — verify MCP server is queried if GitHub MCP is enabled
- [ ] Vision: Ask "What's on my screen?" — verify `describe_screen` tool fires and returns accurate output
- [ ] Dashboard: Observe live LangGraph execution graph update during a multi-step query
- [ ] Daemon: Restart systemd service mid-query, verify response completes after restart

---

## Migration Path from v4.0.0

| Component | v4.0.0 | v5.0.0 |
|-----------|--------|--------|
| Agent loop | `ReActAgent` + `AgentOrchestrator` | `AmadeusGraph` (LangGraph) |
| Vector memory | `QdrantMemoryService` (local file) | `TurbovecMemoryService` + optional Qdrant archival |
| Tool registry | Custom `plugins/` | `ToolRegistry` + MCP client |
| Vision | None | `VLMAdapter` + `vision_tools.py` |
| Frontend | Telegram + CLI only | Telegram + CLI + Next.js dashboard |
| Deployment | Docker Compose or manual | Docker Compose + systemd + optional Tauri |

The migration is **non-breaking at the API level**. All existing REST endpoints, the Telegram transport, the CLI transport, and the JWT auth system remain unchanged. The swap from Qdrant to Turbovec is transparent to callers because both implement the same `store()` / `retrieve()` interface.

---

## Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| LangGraph HITL integration with existing `ConfirmationCallback` requires adapter layer | Medium | Medium | Wire `interrupt_before` to call `ConfirmationCallback.request_approval()` from the `hitl_node`; keep callback interface unchanged |
| Turbovec 4-bit quantization reduces recall on short memory snippets (<50 tokens) | Low | Low | Use 8-bit quantization for memory entries shorter than 50 tokens; benchmark before shipping |
| MCP server process lifecycle management (zombie processes on crash) | Medium | Low | Use `asyncio.subprocess` with `SIGTERM` cleanup in `ToolRegistry.disconnect_mcp_server()` |
| LangGraph checkpoint DB grows unboundedly over long sessions | Low | Medium | Schedule weekly `prune_graph_checkpoints()` that deletes threads older than 30 days |
| VLM local inference (LLaVA 7B) exceeds available RAM on 8 GB machines | Medium | Low | Default `VLM_PROVIDER=gemini_flash`; gate local LLaVA on `RAM > 12 GB` check at startup |

---

## Versioning and Release

- `v5.0.0-alpha` — Phases 0–2 complete (security, LangGraph, Turbovec)
- `v5.0.0-beta` — Phase 3 (MCP) and Phase 6 (Daemon Hardening) complete. Phases 4 (Vision) and 5 (Dashboard) were intentionally skipped.
- `v5.0.0-rc1` / `v5.0.0` — Final verification, cleanup, and stable release.

Each phase merges to `develop`, releases to `main` only when all verification checklist items pass.

---

*Last updated: June 2026*
