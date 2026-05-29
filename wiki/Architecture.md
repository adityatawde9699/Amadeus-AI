# Architecture

Amadeus follows **Clean Architecture** with strict layer separation. Dependencies only flow inward — the Core layer has zero external imports.

---

## Layer Overview

```
┌──────────────────────────────────────────────────┐
│                 CLIENT LAYER                     │
│   HTTP / REST · WebSocket · Telegram · CLI       │
└─────────────────────┬────────────────────────────┘
                      │
┌─────────────────────▼────────────────────────────┐
│         TRANSPORT LAYER  (src/transports/)       │
│  fastapi_transport.py  — FastAPI ASGI app        │
│  telegram_transport.py — Telegram webhook        │
│  cli_transport.py      — Direct CLI runner       │
└─────────────────────┬────────────────────────────┘
                      │  Depends()
┌─────────────────────▼────────────────────────────┐
│       APPLICATION LAYER  (src/app/)              │
│  AmadeusService · CognitiveCore · PlanEngine     │
│  ConversationManager · ToolDispatcher            │
│  ArgumentExtractor · ResponseComposer            │
│  AutonomousObservationLoop                       │
└─────────────────────▼────────────────────────────┘

                      │
         ┌────────────┴────────────┐
         │                        │
┌────────▼─────────┐   ┌──────────▼───────────────┐
│  CORE            │   │  INFRASTRUCTURE           │
│  (src/core/)     │   │  (src/infra/)             │
│                  │   │                           │
│  Domain models   │   │  LLM adapters             │
│  Interfaces/ABCs │   │  Qdrant memory service    │
│  Exceptions      │   │  Redis / PostgreSQL        │
│  Settings        │   │  Tools (53 registered)    │
│                  │   │  ModelManager             │
│  (no external    │   │  Search router            │
│   imports)       │   │  Messaging adapters       │
└──────────────────┘   └───────────────────────────┘
```

**Dependency Injection** is handled by `dependency-injector` in `src/container.py`. The `Container` wires all singletons — LLM router, cache, tool registry, conversation repo, goal repo, and `AmadeusService` — at startup.

---

## Request Lifecycle

A request passes through these stages regardless of transport:

```
Client (HTTP / Telegram / CLI)
  │
  ▼  1. Transport receives message, builds RequestContext
  │
  ▼  2. AmadeusService.process_task() called with context
  │     ├─ Check Redis LLM response cache (1 h TTL)
  │     ├─ Retrieve top-3 semantic memories from Qdrant
  │     └─ Dispatch to AgentOrchestrator queue
  │
  ▼  3. AgentOrchestrator routes by ML intent (SVM → keyword fallback)
  │     Selects: general / system / research agent
  │
  ▼  4. ReActAgent loop (max 4 iterations)
  │     ├─ Thought → LLMRouter.generate()
  │     ├─ Tool call → ToolExecutor (HITL gate for destructive ops)
  │     └─ Observation → next iteration or FINISH
  │
  ▼  5. Response stored in PostgreSQL + Qdrant → returned to transport
```

---

## LLM Routing Pipeline

Every generation request flows through `LLMRouter`, which checks Redis daily-quota counters before dispatching:

```
Incoming Request
       │
       ▼
  LlamaCpp  ──(SLM_MODEL_PATH or auto-downloaded GGUF)──▶  ✅ Response
  (local, unlimited, offline)
       │ not configured / no model
       ▼
  Groq      ──(quota < 14,400/day?)──▶  ✅ Response
  (free tier, Llama 3.3 70B)
       │ exhausted
       ▼
  Gemini    ──(quota < 1,500/day?)──▶  ✅ Response
  (free tier, Gemini 2.5 Flash)
       │ exhausted
       ▼
  🚫 LLMRateLimitError → transport returns error message
```

**LOCAL_ONLY_MODE=true** disables all cloud providers — only LlamaCpp is used.

### Complexity Routing

| Value | Behaviour |
|---|---|
| `"auto"` | Score the prompt and choose the best tier |
| `"simple"` | Local-only (LlamaCpp) |
| `"normal"` | Local first, cloud fallback |
| `"high"` | Cloud-first (Groq → Gemini), local as last resort |

---

## Model Resolution

`ModelManager` (`src/infra/model_manager.py`) governs all local model lifecycle:

```
resolve_embed_model()
  ├─ Check MODEL_DIR/embed/<safe_name>/config.json  → load from local dir
  ├─ MODEL_DOWNLOAD_ENABLED=true → snapshot_download() into Model/embed/
  └─ Fallback → HuggingFace global cache (model ID string)

resolve_gguf_model()
  ├─ SLM_MODEL_PATH set and exists → use directly
  ├─ Model/<SLM_MODEL_FILENAME> exists → use it
  ├─ SLM_MODEL_REPO_ID + SLM_MODEL_FILENAME set → hf_hub_download()
  └─ None → LlamaCpp disabled
```

All models are stored under `Model/` inside the project root, configurable via `MODEL_DIR`.

---

## Memory Architecture

Amadeus uses a two-tier active memory system:

| Tier | Technology | Purpose | Latency |
|---|---|---|---|
| **L1 Flash Cache** | NumPy float32 ring buffer (100 entries, ~307 KB RAM) | Intercepts Qdrant for recently-accessed memories | ~1 µs |
| **L2 Qdrant (Semantic)** | `all-MiniLM-L6-v2` 384-dim vectors + cosine similarity | Long-term cross-session recall with recency/importance weighting | ~5 ms |

Identity memories (`subtype="identity"`, `recency_decay=1.0`) never decay. Contradiction resolution: if a new identity memory has cosine similarity > 0.90 with an existing one, the older entry is deleted before insert.

---

## Goal Management

The `GoalRepository` tracks long-horizon objectives across sessions:

| Tool | Description |
|---|---|
| `create_goal` | Define a new multi-step objective |
| `update_goal` | Transition status: `active` → `completed` / `abandoned` |
| `list_active_goals` | Retrieve all currently active goals for context injection |

Goals are persisted in PostgreSQL via `GoalORM` and injected into the DI container as `_GoalRepoProxy`.

---

## Proactive Observation Loop

`AutonomousObservationLoop` fires background checks at `PROACTIVE_CHECK_INTERVAL_MINUTES` intervals:

- **Rate limiting**: At most `PROACTIVE_MESSAGE_LIMIT_PER_HOUR` dispatches per `session_id` per hour.
- **Dry-run mode**: `PROACTIVE_DRY_RUN=true` logs intent without dispatching to transport — safe for development.
- Task stored as `self._task`; done-callback logs unhandled exceptions. `stop()` cancels cleanly.

---

*← [[Home]] | [[Core-Systems]] →*
