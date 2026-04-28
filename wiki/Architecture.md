# Architecture

Amadeus follows **Clean Architecture** with four strict layers. Dependencies only flow inward — the Core layer has zero external dependencies.

---

## Layer Overview

```
┌──────────────────────────────────────────────┐
│              CLIENT LAYER                    │
│    HTTP / REST · WebSocket · Telegram        │
│         WhatsApp · Email                     │
└────────────────────┬─────────────────────────┘
                     │
┌────────────────────▼─────────────────────────┐
│           API LAYER  (src/api/)              │
│  JWT Auth · Rate Limiter · Audit Logger      │
│  /chat  /tasks  /voice  /llm  /webhooks      │
└────────────────────┬─────────────────────────┘
                     │  Depends()
┌────────────────────▼─────────────────────────┐
│       APPLICATION LAYER  (src/app/)          │
│  AmadeusService · SemanticToolRouter         │
│  AgentOrchestrator · VoiceService            │
└────────────────────┬─────────────────────────┘
                     │
        ┌────────────┴────────────┐
        │                        │
┌───────▼──────┐     ┌───────────▼──────────────┐
│  CORE        │     │  INFRASTRUCTURE           │
│  (src/core/) │     │  (src/infra/)             │
│              │     │                           │
│  Domain      │     │  LLM Adapters             │
│  Interfaces  │     │  Qdrant + Flash Cache     │
│  Exceptions  │     │  Redis · PostgreSQL        │
│  Config      │     │  Whisper STT · Edge TTS   │
│              │     │  Tools (60+)              │
│  (no external│     │  WorkspaceIndexer         │
│   imports)   │     │  Messaging adapters       │
└──────────────┘     └───────────────────────────┘
```

**Dependency Injection** is handled by `dependency-injector` in `src/container.py`. The `Container` class wires all singletons — LLM router, cache, tool registry, conversation repo, and the main `AmadeusService` — at startup.

---

## Request Lifecycle

A `POST /api/v1/chat` request passes through six stages:

```
Client
  │
  ▼  1. JWT verification (HS256, requires exp claim in production)
  │
  ▼  2. Rate limiting (SlowAPI — keyed by JWT sub, falls back to IP)
  │
  ▼  3. AmadeusService.handle_command()
  │     ├─ Check Redis LLM response cache (1h TTL)
  │     ├─ Store user message in PostgreSQL + Qdrant
  │     └─ Multi-step? → AgentOrchestrator
  │         Single-step? → _process_command_internal()
  │
  ▼  4. SemanticToolRouter.route()          ← Stage 1: cosine sim (<10ms)
  │     └─ Confidence < 0.50? → LLM triage  ← Stage 2: LlamaCpp/Groq
  │
  ▼  5. Tool execution (ToolExecutor, with HITL gate for destructive ops)
  │     └─ LLMRouter.generate() composes a natural response
  │
  ▼  6. Store response in PostgreSQL + Qdrant → return ChatResponse
```

---

## LLM Routing Pipeline

Every generation request flows through `LLMRouter`, which checks Redis daily-quota counters before dispatching:

```
Incoming Request
       │
       ▼
  LlamaCpp  ──(SLM_MODEL_PATH set? offline GGUF)──▶  ✅ Response
  (local, unlimited)
       │ not configured
       ▼
  Ollama    ──(running locally?)──▶  ✅ Response
  (local, unlimited)
       │ not running
       ▼
  Groq      ──(quota < 14,400/day?)──▶  ✅ Response
  (free tier, Llama 3.3 70B)
       │ exhausted
       ▼
  Gemini    ──(quota < 1,500/day?)──▶  ✅ Response
  (free tier, Gemini 2.5 Flash)
       │ exhausted
       ▼
  OpenAI    ──(key configured?)──▶  ✅ Response
  (paid, GPT-4o-mini, emergency only)
       │ no key
       ▼
  🚫 LLMRateLimitError → HTTP 503
```

### Complexity Routing

The router accepts a `complexity` hint:

| Value | Behaviour |
|---|---|
| `"auto"` | Score the prompt and choose the best tier |
| `"simple"` | Local-only (LlamaCpp / Ollama) |
| `"normal"` | Local first, cloud fallback |
| `"high"` | Cloud-first (Groq → Gemini → OpenAI), local as last resort |

---

## Voice Pipeline

```
Audio Bytes (WebSocket /api/v1/ws/voice)
       │
       ▼  faster-whisper  (CPU / CUDA, int8, non-blocking via executor)
Transcribed Text
       │
       ▼  LLMRouter (local-first)
LLM Response Text
       │
       ▼  Edge TTS  (en-US-JennyNeural, async streaming, Redis-cached)
Audio Bytes  ──▶  Client
```

The voice WebSocket protocol sends three frames per turn:

1. `{"type": "transcription", "text": "..."}` — what was heard
2. `{"type": "response_text", "text": "..."}` — the AI reply
3. Binary frame — TTS audio bytes (MP3)

---

## Memory Architecture

Amadeus uses a three-tier memory system:

| Tier | Technology | Purpose | Latency |
|---|---|---|---|
| **L1 Flash Cache** | NumPy float32 ring buffer (100 entries, ~307 KB RAM) | Intercepts Qdrant for recently-accessed memories | ~1 µs |
| **L2 Qdrant (Semantic)** | `all-mpnet-base-v2` 768-dim vectors + cosine similarity | Long-term cross-session recall with recency/importance weighting | ~5 ms |
| **L3 Knowledge Graph** | SQLite via SQLAlchemy (EntityORM + RelationshipORM SPO triples) | Structured episodic memory — relationships between entities | ~2 ms |

The L1 cache is invalidated on `clear_conversation()`. Identity memories (subtype `"identity"`, importance `1.0`) never decay in the L2 ranking formula.

---

*← [[Home]] | [[Core-Systems]] →*
