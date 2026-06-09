<div align="center">

# Amadeus AI v5.0.0-alpha

**A secure autonomous AI operating layer built on Clean Architecture — featuring a plan-driven cognitive runtime, persistent execution graphs, and a dynamic plugin system for local devices.**

[![CI Pipeline](https://github.com/adityatawde9699/Amadeus-AI/actions/workflows/main.yml/badge.svg)](https://github.com/adityatawde9699/Amadeus-AI/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.118%2B-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE.txt)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

> **Tech Stack:**
> `Python 3.11+` · `FastAPI` · `SQLAlchemy 2.0` · `Groq (Llama 3.3)` · `Gemini` · `Redis` · `Turbovec` · `PostgreSQL` · `JWT Auth` · `Telegram` · `Docker` · `sentence-transformers` · `llama-cpp-python`

</div>

---

## 1. Problem Statement

Building a secure autonomous AI operating layer that is both capable and safe in production is unsolved by any single off-the-shelf tool:

| Pain Point | Reality |
|---|---|
| **Brittle Agent Loops** | Standard ReAct loops are fragile and lose state. There is no explicit execution graph to audit or resume. |
| **Monolithic Capabilities** | Adding new tools requires modifying core code. There is no standard for hot-loading third-party plugins. |
| **No Execution Policy** | Tool-calling agents often lack a deterministic security layer to block high-risk actions based on user permissions. |
| **Docker Dependency** | Most sandboxes require Docker. There is often no lightweight local alternative for restricted environments. |
| **No offline / privacy mode** | Cloud-only inference means every message leaves the machine. Local GGUF options are often secondary. |
| **Memory amnesia** | Assistants lose context between sessions. Semantic search over past conversations is often unimplemented. |

---

## 2. What is Amadeus?

**Amadeus is a secure autonomous AI operating layer** — a persistent cognitive runtime that acts as the execution layer for autonomous operations. It is not just a chatbot; it is a **headless daemon** designed to plan, act, verify, and remember.

It is a **clean-architecture system** with the following defining properties:

### Cognitive Core Architecture (LangGraph)
Replaces implicit chat loops with a deterministic **LangGraph async state machine**. Every task is decomposed into an explicit execution graph (`Plan` → `PlanStep` → `Observation` → `Reflection`), allowing Amadeus to pause, audit, resume, and recover from failures.

### Dynamic Plugin System
Amadeus features a **hot-pluggable tool architecture**. New capabilities can be added by simply dropping `.py` files into the `plugins/` directory. The agent can even **manage its own plugins** at runtime, writing and registering new tools autonomously.

### Tool Execution Policy Engine
A centralized **security gatekeeper** evaluates every tool call. It maps tools to `RiskLevels` (LOW to CRITICAL) and enforces `PermissionProfiles` (READ_ONLY vs SYSTEM_FULL), ensuring the agent never crosses safety boundaries without explicit authorization.

### Local-First & Cloud-Fallback
A **priority-ordered fallback chain** routes inference:
```
LlamaCpp (local GGUF) → Groq (Llama 3.3 70B) → Gemini 2.5 Flash
```
`LOCAL_ONLY_MODE=true` ensures 100% privacy by disabling all cloud providers.

### 70+ Sandboxed Tools
Amadeus executes a categorised registry spanning:
- **System Control**: launch apps, terminate processes, volume, brightness, screenshots
- **Network**: diagnostics, IP discovery, host pinging
- **Filesystem**: sandboxed read/write/copy/move/search
- **Productivity**: goals, tasks, reminders, notes, Pomodoro
- **Agentic**: `manage_plugins`, `search_codebase`, `decompose_goal`

### Persistent Episodic Memory
Every plan, step, tool result, and reflection is persisted in PostgreSQL. This allows for a complete behavioral audit and enables the agent to learn from past successes and failures.

---

## 3. Solution Summary

Amadeus solves each pain point with a concrete, implemented mechanism:

| Pain Point | Amadeus Solution |
|---|---|
| Brittle Agent Loops | **Cognitive Core** async state machine with explicit execution graphs |
| Monolithic Capabilities | **Dynamic Plugin System** for hot-loading tools from `plugins/` |
| No Execution Policy | **Tool Policy Engine** enforcing risk levels and permissions |
| Docker Dependency | **Dual Sandbox**: epemeral Docker containers OR local multiprocessing |
| No offline mode | LlamaCpp priority; `LOCAL_ONLY_MODE=true` for 100% privacy |
| Memory amnesia | Persistent SQL episodic memory + Turbovec semantic long-term memory |

---

## 4. Features

### Autonomous Agent Lifecycle
- **Plan-Driven Reasoning**: Decomposes complex tasks into actionable sub-goals before execution.
- **Self-Reflection**: Evaluates tool outputs and adapts plans if an action fails or returns an error.
- **Durable State**: Process restarts do not wipe active tasks; the episodic memory retains full context.
- **Proactive Health Watcher**: Background loop monitors system resources (CPU, RAM, Battery) and alerts the user proactively.

### Tool Execution Engine
- **70+ Built-in Tools** across categories: OS Control, Network, Filesystem, Productivity, and Research.
- **Human-in-the-Loop (HITL)**: Destructive or high-risk actions (e.g., `terminate_process`) require explicit user approval.
- **Multi-Sandbox Support**: Runs untrusted code in Docker containers or an isolated local process.

### Omni-Workspace RAG (Hybrid Search)
- **WorkspaceIndexer**: Hybrid BM25 + dense vector retrieval over local project files.
- **Context-Augmented Chunking**: Metadata enrichment for high-precision retrieval of code and documentation.
- **search_workspace Tool**: Enables the agent to search its own codebase or local projects to answer technical questions.

### Security & Safety
- **Prompt Injection Resistance**: `<user_task>` XML boundaries + control token neutralization.
- **Authorization Guard**: Telegram chat ID allowlists and WhatsApp HMAC verification.
- **Secure Secret Handling**: Auto-generated ephemeral keys and persistent secret tokens with strict file permissions.

---

## 5. System Requirements

### Runtime Environment

| Component | Minimum | Recommended | Notes |
|-----------|---------|-------------|-------|
| **Python** | 3.11 | 3.12 | 3.10 and below not supported |
| **RAM** | 2 GB | 8 GB | 2 GB for API-only (no local model); 4–8 GB for local GGUF inference |
| **Disk** | 3 GB | 10 GB | Includes Whisper `small` (~460 MB), Turbovec data, logs, and optional GGUF models (2–8 GB each) |
| **CPU** | 4-core x86-64 | 8-core+ | Multi-core required for concurrent LlamaCpp inference; ARM64 (Apple M-series) also supported |
| **GPU** | Not required | CUDA 11.8+ | Optional: faster Whisper STT; LlamaCpp `n_gpu_layers` offloading |
| **OS** | Linux / macOS / Windows 10+ | Ubuntu 22.04 LTS | Windows supported; Linux recommended for production Docker deployments |

### External Services

| Service | Version | Mode | Purpose |
|---|---|---|---|
| **PostgreSQL** | 15+ | Production | Conversation history, tasks, knowledge graph, user accounts |
| **SQLite** | 3.35+ | Development only | Zero-config alternative to PostgreSQL (not suitable for multi-worker deployments) |
| **Redis** | 6+ | Recommended | Rate limiting, LLM daily quota tracking, TTS + tool result caching. Falls back to in-memory if unavailable. |
| **Turbovec** | 0.7+ | Recommended | Vector memory store for long-term semantic recall. Runs local file-based by default (no server needed) with massive 4-bit compression. |
| **Docker** | 24+ | Optional | Required only for the Python code-execution sandbox (`execute_python_script` tool) |

### LLM Model Requirements *(if using local inference)*

| Model Format | RAM Required | Example |
|---|---|---|
| GGUF Q4_K_M (3B) | ~3 GB | Llama-3.2-3B, Qwen2.5-3B |
| GGUF Q4_K_M (7B) | ~5 GB | Llama-3.1-7B, Gemma-2-9B |
| GGUF Q4_K_M (13B) | ~8 GB | Llama-2-13B |

> **Tip:** Set `SLM_MODEL_PATH` to your `.gguf` file path. No GPU required — LlamaCpp runs fully on CPU. Leave `SLM_MODEL_PATH` unset to skip local inference and use cloud providers only.

### Minimum Viable Setup (no local models, cloud APIs only)

```
Python 3.11 + 1 GB RAM + GROQ_API_KEY (free)
```
Redis and Turbovec are optional — the daemon gracefully degrades without them.

---

## 6. Setup & Installation

### Prerequisites

1. [Python 3.11+](https://www.python.org/downloads/)
2. [`uv`](https://docs.astral.sh/uv/) (recommended) or `pip`
3. [Docker & Docker Compose](https://docs.docker.com/get-docker/) (for containerized setup)
4. At minimum one LLM API key (Groq is free and recommended as primary)

### Clone the Repository

```bash
git clone https://github.com/adityatawde9699/Amadeus-AI.git
cd Amadeus-AI
```

### Environment Variables

Copy the example and fill in your values:

```bash
cp .env.example .env
```

**Required variables:**

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | JWT signing secret — generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `GROQ_API_KEY` | Groq API key — [console.groq.com](https://console.groq.com) (free tier: 14,400 req/day) |
| `GEMINI_API_KEY` | Google Gemini key — [makersuite.google.com](https://makersuite.google.com/app/apikey) |
| `POSTGRES_PASSWORD` | Production DB password — the default `amadeus_password` is a development placeholder only |
| `DATABASE_URL` | Database connection string (defaults to PostgreSQL for multi-worker safety) |

**Optional variables:**

| Variable | Description |
|----------|-------------|
| `REDIS_URL` | Redis for caching + quota tracking (default: `redis://localhost:6379/0`) |
| `WEATHER_API_KEY` | OpenWeatherMap API key |
| `NEWS_API_KEY` | NewsAPI key |
| `TAVILY_API_KEY` | Tavily deep search |
| `SENTRY_DSN` | Sentry error tracking DSN |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token — required for Telegram channel |
| `TELEGRAM_WEBHOOK_SECRET` | Secret header for Telegram webhook validation |
| `EMAIL_IMAP_SERVER` | IMAP server hostname (e.g. `imap.gmail.com`) |
| `EMAIL_SMTP_SERVER` | SMTP server hostname (e.g. `smtp.gmail.com`) |
| `EMAIL_SMTP_PORT` | SMTP port (default: `587`) |
| `EMAIL_ADDRESS` | Sender email address |
| `EMAIL_APP_PASSWORD` | Email app password (Gmail: generate in Account settings) |
| `ENV` | `development` / `staging` / `production` |

### Option A — Local Installation (without Docker)

```bash
# Install dependencies
uv sync --all-extras --dev

# Run database migrations
uv run alembic upgrade head

# Start via FastAPI transport
uv run python -m src.transports.fastapi_transport

# Or via CLI transport for testing
uv run python -m src.transports.cli_transport
```

### Option B — Docker (Development)

```bash
# Starts API + PostgreSQL
docker-compose up --build
```

### Option C — Docker (Production)

```bash
docker-compose --profile prod up --build -d
```

The production profile runs gunicorn with 4 Uvicorn workers (`UvicornWorker`) and resource limits (2 CPU / 1 GB RAM).

---

## 7. API Documentation

The API base path is `/api/v1`. Interactive docs are available at `http://localhost:8000/docs` when `DEBUG=true`.

All endpoints except `/health` and `/api/v1/llm/*` require a **JWT Bearer token** in the `Authorization` header.

### Authentication

There is no built-in user registration endpoint at this time. Tokens must be generated externally using the `SECRET_KEY` with HS256 algorithm. See `src/api/middleware/authentication.py`.

### Endpoints

#### System

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | No | Liveness check (load balancer probe) |
| `GET` | `/` | No | API info and version |
| `GET` | `/api/v1/health/detailed` | No | Detailed health with DB/Redis status |
| `GET` | `/api/v1/metrics` | No | Prometheus metrics |

#### Chat

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/chat` | Yes | Send a message to the assistant |
| `GET` | `/api/v1/chat/stream` | Yes | **SSE streaming** — real-time token-by-token response |
| `GET` | `/api/v1/chat/history` | Yes | Retrieve conversation history by session |
| `GET` | `/api/v1/chat/tools` | Yes | List all available tools by category |
| `POST` | `/api/v1/chat/clear` | Yes | Clear conversation history |

**SSE streaming example:**
```bash
curl -N -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/chat/stream?message=Tell+me+a+joke"
# Streams: data: {"delta": "Why"} ... data: [DONE]
```

**Chat request body:**
```json
{
  "message": "What is the weather in Mumbai?",
  "source": "api",
  "session_id": "optional-existing-session-id",
  "request_id": "optional-idempotency-key"
}
```

**Chat response body:**
```json
{
  "response": "The weather in Mumbai, IN: Haze. Temperature is 29.5°C (feels like 34.2°C). Humidity is 78%...",
  "source": "api",
  "session_id": "uuid-session-id",
  "tools_used": []
}
```

#### Messaging

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/messaging/send` | Yes | Send outbound message (Telegram / Email) |
| `GET` | `/api/v1/messaging/status` | No | Check which channels are configured |
| `POST` | `/api/v1/webhooks/telegram` | Secret token | Receive inbound Telegram updates |

**Send message request:**
```json
{
  "channel": "telegram",
  "to": "123456789",
  "message": "Hello from Amadeus!"
}
```

#### Voice

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `WS` | `/api/v1/ws/voice` | Yes (via query param) | Real-time voice streaming WebSocket |

**Voice WebSocket protocol:**
1. Client sends raw audio bytes (PCM / WAV chunk)
2. Server responds with three messages in sequence:
   - `{"type": "transcription", "text": "what you said"}` — STT output
   - `{"type": "response_text", "text": "assistant reply"}` — LLM response
   - Binary frame — TTS audio bytes

#### Tasks

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/tasks` | Yes | Create a new task |
| `GET` | `/api/v1/tasks` | Yes | List tasks (filter by status) |
| `PATCH` | `/api/v1/tasks/{id}/complete` | Yes | Mark task complete |
| `DELETE` | `/api/v1/tasks/{id}` | Yes | Delete a task |

#### LLM Usage (Informational — no auth)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/v1/llm/usage` | No | Daily LLM usage report per provider |

---

## 8. Full Tech Stack

### Runtime & Language
- **Python 3.11 / 3.12** — primary language
- **Docker** — containerization (multi-stage build)

### Framework & API
- **FastAPI 0.118+** — async web framework
- **Uvicorn** — ASGI server (development)
- **Gunicorn + UvicornWorker** — production multi-worker setup
- **SlowAPI** — rate limiting (IP-based, per-minute window)
- **python-jose** — JWT encoding and validation

### Database & ORM
- **SQLAlchemy 2.0 (asyncio)** — async ORM
- **Alembic** — database migrations
- **PostgreSQL 15** (production) via `asyncpg`
- **SQLite** (development) via `aiosqlite`
- **Redis 5+** — caching layer (via `redis-py` async client)

### AI & LLM
- **Groq API (Llama 3.3 70B)** — Cloud primary LLM (free tier)
- **Google Generative AI (Gemini 2.5 Flash)** — Secondary cloud LLM
- **Turbovec** — vector database for semantic long-term memory
- **LLMRouter** — Redis-backed daily-quota-aware routing engine with atomic `INCR`/`EXPIRE`
- **SemanticToolRouter** — sentence-transformers based zero-training tool intent triaging
- **WorkspaceIndexer** — hybrid BM25 + dense vector retrieval engine for project RAG

### Voice
- **faster-whisper** — CTranslate2 Whisper STT (CPU/CUDA)
- **edge-tts** — Microsoft Edge TTS (free, cloud-based)
- **SpeechRecognition + pyttsx3** — alternative local TTS/STT stack *(optional)*

### Validation & Configuration
- **Pydantic v2 + pydantic-settings** — type-safe settings from environment
- **python-dotenv** — `.env` file loading

### Dependency Injection
- **dependency-injector 4.41+** — IoC container (`src/container.py`)

### Observability
- **Structlog** — structured JSON logging
- **Sentry SDK** — error monitoring
- **prometheus-fastapi-instrumentator** — Prometheus metrics

### Development & Quality
- **pytest + pytest-asyncio** — testing framework
- **testcontainers[postgres]** — integration tests with containerized PostgreSQL
- **httpx** — async HTTP client for FastAPI TestClient
- **Ruff** — linting and formatting
- **Black** — code formatter
- **Mypy** — static type checking
- **Bandit** — security scanning
- **pip-audit** — dependency vulnerability auditing
- **uv** — dependency management and virtual environments
- **rank-bm25** — lexical search for RAG
- **sentence-transformers** — dense vector embeddings for memory and routing

---

## 9. System Architecture

### Clean Architecture — Layer Overview

```mermaid
block-beta
  columns 1

  block:clients["🌐  CLIENT LAYER"]:1
    columns 3
    A["🖥️ HTTP / REST\nclients"] B["📨 Telegram Bot"] C["💻 CLI"]
  end

  space

  block:transports["🔀  TRANSPORT LAYER  —  src/transports/"]:1
    columns 3
    D["⚡ fastapi_transport\nFastAPI + JWT"] E["📨 telegram_transport\nWebhook handler"] F["💻 cli_transport\nDirect runner"]
  end

  space

  block:app["🧠  APPLICATION LAYER  —  src/app/"]:1
    columns 3
    J["🤖 AmadeusService\nOrchestrator"] K["📝 ConversationManager\nHistory · DB Sync"] L["🔄 AgentOrchestrator\nReAct loop"]
    J2["🔍 ArgumentExtractor\nLLM · Regex"] K2["⚙️ ToolDispatcher\nTimeouts · Cache"] L2["✍️ ResponseComposer\nPrompts"]
  end

  space

  block:core["💎  CORE  —  src/core/"]:1
    columns 4
    M["📐 Domain\nModels"] N["🔌 LLMAdapter\nABC"] O["⚙️ Settings\nPydantic"] P["❌ Exceptions\nHierarchy"]
  end

  space

  block:infra["🔩  INFRASTRUCTURE  —  src/infra/"]:1
    columns 3
    block:llmblock["🤖 LLM"]:1
      columns 1
      Q["LlamaCpp  (local)"] S["Groq / Gemini"]
    end
    block:datablock["💾 Data"]:1
      columns 1
      T["PostgreSQL"] U["Redis Cache"] V["Turbovec Vectors"]
      V2["Flash Memory Cache"]
    end
    block:svcblock["🛠️ Services"]:1
      columns 1
      X["DDG→Tavily\nSearch Router"] Y["Tools: info /\nproductivity / system / goals"]
      Z["ModelManager\nAuto-download"]
    end
  end

  clients --> transports
  transports --> app
  app --> core
  app --> infra
  core --> infra
```

### Request Lifecycle — Chat Endpoint

```mermaid
sequenceDiagram
    autonumber
    participant Client
    participant FastAPI as ⚡ FastAPI
    participant Auth as 🔐 JWT Auth
    participant Amadeus as 🤖 AmadeusService
    participant Classifier as 📊 ML Classifier
    participant Agent as 🔄 Agent Loop
    participant Router as 🔀 LLMRouter
    participant LlamaCpp as 💻 LlamaCpp
    participant Groq as ☁️ Groq
    participant Cache as ⚡ Redis Cache
    participant DB as 🗄️ PostgreSQL

    Client->>FastAPI: POST /api/v1/chat
    FastAPI->>Auth: Verify JWT Bearer
    Auth-->>FastAPI: ✅ User claims
    FastAPI->>Amadeus: process_message()
    Amadeus->>Cache: Cache lookup (1h TTL)
    alt Cache HIT
        Cache-->>Amadeus: Cached response
    else Cache MISS
        Amadeus->>Classifier: route(message)
        Note over Classifier: SemanticToolRouter (cosine sim)
        Classifier-->>Amadeus: tool_name (< 10ms)
        Amadeus->>Agent: run_agent_loop()
        Agent->>Router: generate(prompt, context)
        Router->>LlamaCpp: is_available()?
        alt LlamaCpp available
            LlamaCpp-->>Router: ✅ Response
        else LlamaCpp not configured
            Router->>Groq: generate()
            Groq-->>Router: ✅ Response
        end
        Router-->>Agent: (response, provider_used)
        Agent-->>Amadeus: final_response
        Amadeus->>Cache: Store response (1h TTL)
        Amadeus->>DB: Persist conversation history
    end
    Amadeus-->>FastAPI: ChatResponse
    FastAPI-->>Client: 200 JSON
```





<div align="center">

<!-- ═══════════════════════════════════════════════════════
     ARCHITECTURE DIAGRAM  —  rendered in browsers / GitHub
     ═══════════════════════════════════════════════════════ -->

<table width="100%" cellspacing="0" cellpadding="0" border="0">

<!-- CLIENT LAYER -->
<tr><td>
<table width="100%" cellspacing="0" cellpadding="0" border="0"
       style="border:1px solid #B5D4F4;border-left:4px solid #378ADD;border-radius:8px;background:#E6F1FB;margin-bottom:0">
<tr>
  <td style="padding:8px 14px 4px">
    <strong style="font-size:11px;letter-spacing:.08em;color:#0C447C">CLIENT LAYER</strong>
  </td>
</tr>
<tr>
  <td style="padding:4px 14px 10px">
    <code style="background:#dbedf9;border:1px solid #B5D4F4;border-radius:4px;padding:2px 8px;font-size:12px;color:#0C447C;margin-right:6px">HTTP / REST clients</code>
    <code style="background:#dbedf9;border:1px solid #B5D4F4;border-radius:4px;padding:2px 8px;font-size:12px;color:#0C447C">WebSocket — voice stream</code>
  </td>
</tr>
</table>
</td></tr>

<!-- ARROW -->
<tr><td align="center" style="padding:4px 0;font-size:18px;color:#888">↓</td></tr>

<!-- API LAYER -->
<tr><td>
<table width="100%" cellspacing="0" cellpadding="0" border="0"
       style="border:1px solid #AFA9EC;border-left:4px solid #7F77DD;border-radius:8px;background:#EEEDFE;margin-bottom:0">
<tr>
  <td style="padding:8px 14px 4px">
    <strong style="font-size:11px;letter-spacing:.08em;color:#26215C">API LAYER</strong>
    &nbsp;<code style="font-size:10px;color:#534AB7;background:none;border:none">src/api/</code>
  </td>
</tr>
<tr>
  <td style="padding:2px 14px 4px">
    <span style="font-size:10px;letter-spacing:.07em;text-transform:uppercase;color:#534AB7">Routes</span><br>
    <code style="background:#dddcf8;border:1px solid #AFA9EC;border-radius:4px;padding:2px 8px;font-size:12px;color:#3C3489;margin:2px 4px 2px 0;display:inline-block">/chat</code>
    <code style="background:#dddcf8;border:1px solid #AFA9EC;border-radius:4px;padding:2px 8px;font-size:12px;color:#3C3489;margin:2px 4px 2px 0;display:inline-block">/tasks</code>
    <code style="background:#dddcf8;border:1px solid #AFA9EC;border-radius:4px;padding:2px 8px;font-size:12px;color:#3C3489;margin:2px 4px 2px 0;display:inline-block">/voice</code>
    <code style="background:#dddcf8;border:1px solid #AFA9EC;border-radius:4px;padding:2px 8px;font-size:12px;color:#3C3489;margin:2px 4px 2px 0;display:inline-block">/health</code>
    <code style="background:#dddcf8;border:1px solid #AFA9EC;border-radius:4px;padding:2px 8px;font-size:12px;color:#3C3489;margin:2px 4px 2px 0;display:inline-block">/llm</code>
  </td>
</tr>
<tr>
  <td style="padding:4px 14px 10px">
    <span style="font-size:10px;letter-spacing:.07em;text-transform:uppercase;color:#534AB7">Middleware &amp; handlers</span><br>
    <code style="background:#dddcf8;border:1px solid #AFA9EC;border-radius:4px;padding:2px 8px;font-size:12px;color:#3C3489;margin:2px 4px 2px 0;display:inline-block">JWT auth</code>
    <code style="background:#dddcf8;border:1px solid #AFA9EC;border-radius:4px;padding:2px 8px;font-size:12px;color:#3C3489;margin:2px 4px 2px 0;display:inline-block">Audit logger</code>
    <code style="background:#dddcf8;border:1px solid #AFA9EC;border-radius:4px;padding:2px 8px;font-size:12px;color:#3C3489;margin:2px 4px 2px 0;display:inline-block">SlowAPI rate limiter</code>
    <code style="background:#dddcf8;border:1px solid #AFA9EC;border-radius:4px;padding:2px 8px;font-size:12px;color:#3C3489;margin:2px 4px 2px 0;display:inline-block">AmadeusError → 400</code>
    <code style="background:#dddcf8;border:1px solid #AFA9EC;border-radius:4px;padding:2px 8px;font-size:12px;color:#3C3489;margin:2px 4px 2px 0;display:inline-block">Generic → 500</code>
  </td>
</tr>
</table>
</td></tr>

<!-- ARROW -->
<tr><td align="center" style="padding:4px 0;font-size:13px;color:#888">↓ &nbsp;<em style="font-size:11px">Depends()</em></td></tr>

<!-- APPLICATION LAYER -->
<tr><td>
<table width="100%" cellspacing="0" cellpadding="0" border="0"
       style="border:1px solid #9FE1CB;border-left:4px solid #1D9E75;border-radius:8px;background:#E1F5EE;margin-bottom:0">
<tr>
  <td style="padding:8px 14px 4px">
    <strong style="font-size:11px;letter-spacing:.08em;color:#04342C">APPLICATION LAYER</strong>
    &nbsp;<code style="font-size:10px;color:#0F6E56;background:none;border:none">src/app/</code>
  </td>
</tr>
<tr>
  <td style="padding:4px 14px 10px">
    <code style="background:#c5edd9;border:1px solid #9FE1CB;border-radius:4px;padding:2px 8px;font-size:12px;color:#085041;margin:2px 4px 2px 0;display:inline-block">AmadeusService <em>(orchestrator)</em></code>
    <code style="background:#c5edd9;border:1px solid #9FE1CB;border-radius:4px;padding:2px 8px;font-size:12px;color:#085041;margin:2px 4px 2px 0;display:inline-block">ConversationManager</code>
    <code style="background:#c5edd9;border:1px solid #9FE1CB;border-radius:4px;padding:2px 8px;font-size:12px;color:#085041;margin:2px 4px 2px 0;display:inline-block">ArgumentExtractor</code>
    <code style="background:#c5edd9;border:1px solid #9FE1CB;border-radius:4px;padding:2px 8px;font-size:12px;color:#085041;margin:2px 4px 2px 0;display:inline-block">ToolDispatcher</code>
    <code style="background:#c5edd9;border:1px solid #9FE1CB;border-radius:4px;padding:2px 8px;font-size:12px;color:#085041;margin:2px 4px 2px 0;display:inline-block">ResponseComposer</code>
    <code style="background:#c5edd9;border:1px solid #9FE1CB;border-radius:4px;padding:2px 8px;font-size:12px;color:#085041;margin:2px 4px 2px 0;display:inline-block">UnifiedSemanticRouter</code>
    <code style="background:#c5edd9;border:1px solid #9FE1CB;border-radius:4px;padding:2px 8px;font-size:12px;color:#085041;margin:2px 4px 2px 0;display:inline-block">VoiceService — STT → LLM → TTS</code>
  </td>
</tr>
</table>
</td></tr>

<!-- SPLIT ARROWS -->
<tr><td>
<table width="100%" cellspacing="0" cellpadding="0" border="0"><tr>
  <td width="30%" align="center" style="padding:4px 0;font-size:12px;color:#888">↓ Core interfaces</td>
  <td width="70%" align="center" style="padding:4px 0;font-size:12px;color:#888">↓ Infrastructure services</td>
</tr></table>
</td></tr>

<!-- CORE + INFRA ROW -->
<tr><td>
<table width="100%" cellspacing="6" cellpadding="0" border="0"><tr valign="top">

  <!-- CORE -->
  <td width="28%">
  <table width="100%" cellspacing="0" cellpadding="0" border="0"
         style="border:1px solid #FAC775;border-left:4px solid #BA7517;border-radius:8px;background:#FAEEDA;height:100%">
  <tr><td style="padding:8px 12px 4px">
    <strong style="font-size:11px;letter-spacing:.08em;color:#412402">CORE</strong>
    &nbsp;<code style="font-size:10px;color:#854F0B;background:none;border:none">src/core/</code>
  </td></tr>
  <tr><td style="padding:4px 12px 10px">
    <code style="background:#f5d998;border:1px solid #FAC775;border-radius:4px;padding:2px 7px;font-size:11px;color:#633806;margin:2px 0;display:block">Domain models</code>
    <code style="background:#f5d998;border:1px solid #FAC775;border-radius:4px;padding:2px 7px;font-size:11px;color:#633806;margin:2px 0;display:block">Interfaces / ABCs</code>
    <code style="background:#f5d998;border:1px solid #FAC775;border-radius:4px;padding:2px 7px;font-size:11px;color:#633806;margin:2px 0;display:block">Config (Settings)</code>
    <code style="background:#f5d998;border:1px solid #FAC775;border-radius:4px;padding:2px 7px;font-size:11px;color:#633806;margin:2px 0;display:block">Exceptions</code>
  </td></tr>
  </table>
  </td>

  <!-- INFRA -->
  <td width="72%">
  <table width="100%" cellspacing="0" cellpadding="0" border="0"
         style="border:1px solid #F5C4B3;border-left:4px solid #D85A30;border-radius:8px;background:#FAECE7">
  <tr><td style="padding:8px 12px 4px">
    <strong style="font-size:11px;letter-spacing:.08em;color:#4A1B0C">INFRASTRUCTURE</strong>
    &nbsp;<code style="font-size:10px;color:#993C1D;background:none;border:none">src/infra/</code>
  </td></tr>
  <tr><td style="padding:4px 12px 10px">
  <table width="100%" cellspacing="4" cellpadding="0" border="0"><tr valign="top">
    <td width="33%">
      <table width="100%" cellspacing="0" cellpadding="6" border="0" style="background:#f8d5c4;border:1px solid #F5C4B3;border-radius:6px">
        <tr><td><strong style="font-size:12px;color:#4A1B0C">LLM router</strong><br><span style="font-size:11px;color:#993C1D">Groq · Gemini adapters</span></td></tr>
      </table>
    </td>
    <td width="33%">
      <table width="100%" cellspacing="0" cellpadding="6" border="0" style="background:#f8d5c4;border:1px solid #F5C4B3;border-radius:6px">
        <tr><td><strong style="font-size:12px;color:#4A1B0C">Cache — Redis</strong><br><span style="font-size:11px;color:#993C1D">llm · tts · tool · search</span></td></tr>
      </table>
    </td>
    <td width="33%">
      <table width="100%" cellspacing="0" cellpadding="6" border="0" style="background:#f8d5c4;border:1px solid #F5C4B3;border-radius:6px">
        <tr><td><strong style="font-size:12px;color:#4A1B0C">Persistence</strong><br><span style="font-size:11px;color:#993C1D">SQLAlchemy · Alembic</span></td></tr>
      </table>
    </td>
  </tr><tr valign="top" style="padding-top:4px">
    <td width="33%" style="padding-top:4px">
      <table width="100%" cellspacing="0" cellpadding="6" border="0" style="background:#f8d5c4;border:1px solid #F5C4B3;border-radius:6px">
        <tr><td><strong style="font-size:12px;color:#4A1B0C">Tools</strong><br><span style="font-size:11px;color:#993C1D">info · productivity · system</span></td></tr>
      </table>
    </td>
    <td width="33%" style="padding-top:4px">
      <table width="100%" cellspacing="0" cellpadding="6" border="0" style="background:#f8d5c4;border:1px solid #F5C4B3;border-radius:6px">
        <tr><td><strong style="font-size:12px;color:#4A1B0C">Speech</strong><br><span style="font-size:11px;color:#993C1D">Whisper STT · Edge TTS</span></td></tr>
      </table>
    </td>
    <td width="33%" style="padding-top:4px">
      <table width="100%" cellspacing="0" cellpadding="6" border="0" style="background:#f8d5c4;border:1px solid #F5C4B3;border-radius:6px">
        <tr><td><strong style="font-size:12px;color:#4A1B0C">Search router</strong><br><span style="font-size:11px;color:#993C1D">DDG → Tavily</span></td></tr>
      </table>
    </td>
    <td width="33%" style="padding-top:4px">
      <table width="100%" cellspacing="0" cellpadding="6" border="0" style="background:#f8d5c4;border:1px solid #F5C4B3;border-radius:6px">
        <tr><td><strong style="font-size:12px;color:#4A1B0C">RAG Engine</strong><br><span style="font-size:11px;color:#993C1D">WorkspaceIndexer</span></td></tr>
      </table>
    </td>
  </tr></table>
  </td></tr>
  </table>
  </td>

</tr></table>
</td></tr>

<!-- ARROW -->
<tr><td align="center" style="padding:4px 0;font-size:18px;color:#888">↓</td></tr>

<!-- DATA LAYER -->
<tr><td>
<table width="100%" cellspacing="0" cellpadding="0" border="0"
       style="border:1px solid #C0DD97;border-left:4px solid #639922;border-radius:8px;background:#EAF3DE;margin-bottom:0">
<tr>
  <td style="padding:8px 14px 4px">
    <strong style="font-size:11px;letter-spacing:.08em;color:#173404">DATA LAYER</strong>
  </td>
</tr>
<tr><td style="padding:4px 14px 10px">
<table width="100%" cellspacing="6" cellpadding="0" border="0"><tr>
  <td width="25%">
    <table width="100%" cellspacing="0" cellpadding="6" border="0" style="background:#d0e8a8;border:1px solid #C0DD97;border-radius:6px;text-align:center">
      <tr><td><strong style="font-size:12px;color:#173404">PostgreSQL</strong><br><span style="font-size:10px;color:#3B6D11">prod</span></td></tr>
    </table>
  </td>
  <td width="25%">
    <table width="100%" cellspacing="0" cellpadding="6" border="0" style="background:#d0e8a8;border:1px solid #C0DD97;border-radius:6px;text-align:center">
      <tr><td><strong style="font-size:12px;color:#173404">SQLite</strong><br><span style="font-size:10px;color:#3B6D11">dev</span></td></tr>
    </table>
  </td>
  <td width="25%">
    <table width="100%" cellspacing="0" cellpadding="6" border="0" style="background:#d0e8a8;border:1px solid #C0DD97;border-radius:6px;text-align:center">
      <tr><td><strong style="font-size:12px;color:#173404">Redis</strong><br><span style="font-size:10px;color:#3B6D11">cache</span></td></tr>
    </table>
  </td>
  <td width="25%">
    <table width="100%" cellspacing="0" cellpadding="6" border="0" style="background:#d0e8a8;border:1px solid #C0DD97;border-radius:6px;text-align:center">
      <tr><td><strong style="font-size:12px;color:#173404">Turbovec</strong><br><span style="font-size:10px;color:#3B6D11">vector DB</span></td></tr>
    </table>
  </td>
</tr></table>
</td></tr>
</table>
</td></tr>

</table>

</div>

</td></tr></table>

### LLM Routing Order

Every request passes through the `LLMRouter` which checks Redis daily-quota counters (atomic `INCR`/`EXPIRE`) before dispatching:

```mermaid
flowchart TD
    A(["📨 Incoming Request"]):::start

    A --> LC{"💻 LlamaCpp\nSLM_MODEL_PATH set?"}
    LC -- "Yes — offline\nGGUF model" --> LCR["💻 LlamaCpp\nLocal · Offline · Free · PRIMARY"]
    LC -- "Not configured" --> B{"🦙 Ollama\nrunning locally?"}

    B -- "Yes — unlimited" --> C["🦙 Ollama\nLocal · Offline · Free"]
    B -- "No / unavailable" --> D{"☁️ Groq\nquota < 14,400/day?"}

    D -- Yes --> E["🟡 Groq\nLlama 3.3 70B · Free tier"]
    D -- Exhausted --> F{"✨ Gemini\nquota < 1,500/day?"}

    F -- Yes --> G["🟠 Gemini 2.5 Flash\nFree tier"]
    F -- Exhausted --> H{"🔑 OpenAI key\nconfigured?"}

    H -- Yes --> I["🔴 OpenAI GPT-4o-mini\nPaid — emergency fallback"]
    H -- No --> J(["🚫 LLMRateLimitError\nHTTP 503"]):::error

    LCR --> K(["✅ Response"]):::ok
    C   --> K
    E   --> K
    G   --> K
    I   --> K

    classDef start fill:#E1F5EE,stroke:#1D9E75,color:#04342C,font-weight:bold
    classDef ok    fill:#EAF3DE,stroke:#639922,color:#173404,font-weight:bold
    classDef error fill:#FCEBEB,stroke:#A32D2D,color:#501313,font-weight:bold

    style LCR fill:#dbedf9,stroke:#378ADD,color:#0C447C,font-weight:bold
    style C   fill:#EAF3DE,stroke:#639922,color:#173404
    style E   fill:#FAEEDA,stroke:#BA7517,color:#412402
    style G   fill:#FAECE7,stroke:#D85A30,color:#4A1B0C
    style I   fill:#FCEBEB,stroke:#c0392b,color:#501313
```

**Quota tracking keys in Redis:**

| Provider | Redis key | Daily limit | TTL |
|----------|-----------|-------------|-----|
| LlamaCpp | — (local GGUF, unlimited) | ∞ | — |
| Ollama | — (local server, unlimited) | ∞ | — |
| Groq | `llm_usage:groq:{date}` | 14,400 req | 86400 s |
| Gemini | `llm_usage:gemini:{date}` | 1,500 req | 86400 s |
| OpenAI | `llm_usage:openai:{date}` | 100 req | 86400 s |

Counters are incremented atomically with `INCR` and set to expire at midnight via `EXPIREAT`. All workers share the same counter, preventing cross-process over-quota.

---

## 10. Usage Examples

### Text Chat

```bash
# Authenticate (generate a JWT externally using SECRET_KEY and HS256)
TOKEN="your.jwt.token"

# Ask a question
curl -X POST "http://localhost:8000/api/v1/chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message": "What is the weather in Delhi?", "source": "curl"}'

# Get current news
curl -X POST "http://localhost:8000/api/v1/chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message": "Give me today'\''s technology news headlines"}'

# Start a Pomodoro timer
curl -X POST "http://localhost:8000/api/v1/chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message": "Start a 25 minute Pomodoro for writing documentation"}'

# Add a task
curl -X POST "http://localhost:8000/api/v1/chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message": "Add task: Review pull requests"}'

# Calculate
curl -X POST "http://localhost:8000/api/v1/chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message": "What is 1234 * 5678?"}'
```

### Conversation History

```bash
# Retrieve history for a session
curl "http://localhost:8000/api/v1/chat/history?session_id=<SESSION_ID>" \
  -H "Authorization: Bearer $TOKEN"

# Clear conversation
curl -X POST "http://localhost:8000/api/v1/chat/clear" \
  -H "Authorization: Bearer $TOKEN"
```

### SSE Streaming

```bash
curl -N -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/chat/stream?message=Summarise+today%27s+news"
```

Each event is a JSON object. The stream ends with `[DONE]`:
```
data: {"delta": "Here"}
data: {"delta": " are"}
data: {"delta": " today's top news ..."}
data: [DONE]
```

### Outbound Messaging

```bash
# Send a Telegram message
curl -X POST http://localhost:8000/api/v1/messaging/send \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"channel": "telegram", "to": "123456789", "message": "Hello from Amadeus!"}'

# Send an email
curl -X POST http://localhost:8000/api/v1/messaging/send \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"channel": "email", "to": "user@example.com", "subject": "Daily Brief", "message": "Your briefing is ready."}'

# Check channel status
curl http://localhost:8000/api/v1/messaging/status
# {"telegram": true, "whatsapp": false, "email": true}
```

### Voice via WebSocket (Python client example)

```python
import asyncio
import websockets

async def voice_session():
    uri = "ws://localhost:8000/api/v1/ws/voice"
    headers = {"Authorization": "Bearer YOUR_JWT_TOKEN"}
    async with websockets.connect(uri, additional_headers=headers) as ws:
        with open("audio_chunk.wav", "rb") as f:
            await ws.send(f.read())
        transcription = await ws.recv()   # {"type": "transcription", "text": "..."}
        response_text = await ws.recv()   # {"type": "response_text", "text": "..."}
        audio_bytes   = await ws.recv()   # binary TTS audio

asyncio.run(voice_session())
```

---

## 11. Project Structure

<details>
<summary><strong>Expand full tree</strong></summary>

```
Amadeus-AI/
│
├── .github/                        # CI/CD workflows and issue templates
│   └── workflows/main.yml          # Lint → test → Docker build
├── CONTRIBUTING.md
├── CHANGELOG.md
├── SECURITY.md
├── CODE_OF_CONDUCT.md
│
├── alembic/                        # Database migration scripts
│   └── versions/
│
├── data/                           # Runtime data (gitignored)
│
├── deploy/
│   └── amadeus.service             # systemd unit for bare-metal Linux
│
├── Model/                          # All local models (managed by ModelManager)
│   └── embed/                      # Embedding models auto-downloaded here
│
├── scripts/
│   ├── generate_training_data.py
│   ├── index_workspace.py
│   └── retrain_classifier.py
│
├── src/
│   ├── container.py                # IoC container — wires all dependencies
│   │
│   ├── transports/                 # ── TRANSPORT LAYER ───────────────────────────
│   │   ├── fastapi_transport.py    # FastAPI app factory, JWT, rate limiting
│   │   ├── telegram_transport.py   # Telegram webhook adapter
│   │   └── cli_transport.py        # Direct CLI runner
│   │
│   ├── api/                        # ── API ROUTES & MIDDLEWARE ────────────────
│   │   ├── middleware/
│   │   │   ├── authentication.py   # JWT Bearer verification (HS256)
│   │   │   ├── rbac.py             # Permission profiles
│   │   │   └── audit_logger.py     # Request ID injection, latency headers
│   │   └── routes/
│   │       ├── chat.py             # POST /chat · GET /chat/stream (SSE)
│   │       ├── messaging.py        # POST /messaging/send
│   │       ├── webhooks.py         # Telegram inbound webhooks
│   │       ├── tasks.py            # CRUD /tasks
│   │       └── health.py           # /health/live · /health/ready
│   │
│   ├── app/                        # ── APPLICATION LAYER ─────────────────────
│   │   └── services/
│   │       ├── amadeus_service.py  # Thin orchestrator
│   │       ├── agent_loop.py       # ReAct agent + AgentOrchestrator
│   │       ├── autonomous_loop.py  # Proactive observation loop
│   │       ├── conversation_manager.py
│   │       ├── argument_extractor.py
│   │       ├── tool_dispatcher.py
│   │       ├── response_composer.py
│   │       ├── semantic_router.py  # Zero-training cosine triage
│   │       └── tool_registry.py
│   │
│   ├── core/                       # ── CORE LAYER (no external deps) ───────
│   │   ├── config.py               # Pydantic-settings typed env schema
│   │   ├── exceptions.py           # AmadeusError hierarchy
│   │   ├── domain/models.py        # Pydantic domain models
│   │   └── interfaces/
│   │       ├── llm.py              # LLMAdapter ABC
│   │       └── repositories.py     # Abstract repository interfaces
│   │
│   └── infra/                      # ── INFRASTRUCTURE LAYER ───────────────
│       ├── model_manager.py        # Auto-download embed + GGUF models
│       ├── llm/
│       │   ├── router.py           # Multi-LLM routing + Redis quota
│       │   ├── llama_cpp_adapter.py
│       │   ├── groq_adapter.py
│       │   └── gemini_adapter.py
│       ├── memory_service.py       # Turbovec + Flash Cache
│       ├── messaging/
│       │   ├── telegram_adapter.py
│       │   └── email_adapter.py
│       ├── cache/cache_service.py  # Redis async client
│       ├── persistence/
│       │   ├── database.py
│       │   ├── orm_models.py       # SQLAlchemy ORM (includes GoalORM)
│       │   └── repositories/
│       ├── search/search_router.py # DuckDuckGo → Tavily
│       └── tools/
│           ├── agent_tools.py      # Goal + schedule tools
│           ├── info_tools.py
│           ├── productivity_tools.py
│           ├── monitor_tools.py
│           └── system_tools.py
│
├── tests/
│   ├── unit/
│   └── integration/
│
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── alembic.ini
└── .env.example
```

</details>

**Layer responsibilities at a glance:**

| Layer | Path | Responsibility |
|-------|------|----------------|
| Transport | `src/transports/` | FastAPI ASGI app · Telegram webhook · CLI runner — each shares the same `AmadeusService` singleton |
| API | `src/api/` | HTTP routing, JWT auth middleware, request/response serialization |
| Application | `src/app/services/` | **Orchestrator** (`AmadeusService`) + focused sub-services: `ConversationManager`, `ArgumentExtractor`, `ToolDispatcher`, `ResponseComposer` |
| Core | `src/core/` | Domain models, interfaces, config, exceptions — zero external deps |
| Infrastructure | `src/infra/` | LLM adapters, DB, cache, memory, search, messaging, tools, `ModelManager` |
| Data | — | PostgreSQL · Redis · Turbovec · Flash Cache |

---

## 12. Testing

### Run All Tests

```bash
# Using uv
uv run pytest tests/ -v --cov=src --cov-report=term-missing

# Using pip
pytest tests/ -v --cov=src --cov-report=term-missing
```

### Run by Marker

```bash
pytest tests/ -m unit        -v          # unit tests only
pytest tests/ -m integration -v          # requires running PostgreSQL
pytest tests/ -m "not slow"  -v          # skip slow tests
```

### Coverage Threshold

| Environment | Threshold | Enforced by |
|-------------|-----------|-------------|
| Local | 80% | `pyproject.toml` `fail_under = 80` |
| CI (GitHub Actions) | 80% | `--cov-fail-under=80` |

### Integration Tests

Integration tests use `testcontainers[postgres]` to spin up a temporary PostgreSQL container — no manual database setup required:

```bash
pytest tests/ -m integration
```

### Load Testing

```bash
locust -f locustfile.py --host http://localhost:8000
```

---

## 13. Deployment Instructions

### Deploy to Railway (Staging — Automated)

Merging a pull request into the `develop` branch triggers automatic deployment to Railway staging via GitHub Actions. The `RAILWAY_TOKEN` secret must be configured in the repository's GitHub Actions secrets.

### Deploy to Railway (Manual)

```bash
npm install -g @railway/cli
railway login && railway link
railway up
```

Set the following environment variables in the Railway dashboard:
- `SECRET_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`
- `DATABASE_URL` (Railway PostgreSQL plugin)
- `REDIS_URL` (Railway Redis plugin)
- `ENV=production`, `DEBUG=false`

### Deploy with Docker Compose

```bash
docker compose up -d

# View logs
docker compose logs -f amadeus

# Run migrations inside the container
docker compose exec amadeus uv run alembic upgrade head
```

### Deploy as a Linux Daemon

```bash
# Copy the unit file
sudo cp deploy/amadeus.service /etc/systemd/system/

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable amadeus
sudo systemctl start amadeus
sudo journalctl -u amadeus -f
```

### Deploy as a Standalone Windows Daemon

The entire backend (including database migrations, local ML models, and API framework) can be compiled into a zero-dependency headless Windows process.

**1. Compilation**  
*(Requires an active python virtual environment)*
```bash
python scripts\build_windows.py
```

**2. Manual Execution**  
To run the background process and automatically validate your `.env` configuration:
```bash
Launch_Amadeus.bat
```
*(Logs are written to `data\logs\amadeus.log`. Stop it via Task Manager)*

**3. Install as a Native Windows Service (Recommended)**  
Launch PowerShell as Administrator to bind the executable to Windows boot:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows_service.ps1
```

The Dockerfile is a **3-stage multi-stage build:**

| Stage | Purpose |
|-------|---------|
| `builder` | Installs Python dependencies |
| `model_cache` | Pre-downloads Whisper `small` model (~460 MB) — eliminates cold-start latency |
| `runtime` | Minimal production image, non-root user (`amadeus`) |

The container entrypoint:
```bash
alembic upgrade head && uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --workers 1
```

---

## 14. Known Limitations

- **No user registration or RBAC**: JWT tokens must be generated externally. There is no `/register` or `/login` endpoint. All authenticated users share the same assistant context unless `session_id` is explicitly scoped per request.
- **Session isolation is caller-scoped**: The `AmadeusService` singleton reads `session_id` from the incoming request at the API layer. Concurrent requests with different session IDs are correctly isolated at the `ConversationManager` level, but share the same singleton service instance — full per-request instance isolation requires the DI container to be refactored to a request-scoped provider.
- **Voice WebSocket — no auth on upgrade**: WebSocket JWT enforcement depends on the client handshake; the server accepts connections and errors downstream if the token is missing.
- **Local TTS/STT resource usage**: Running `faster-whisper` (`small` model) and Edge TTS simultaneously on a single CPU core may cause response latency of 1–5 seconds per voice round-trip.
- **Semantic memory**: Turbovec runs entirely locally. If memory is disabled, retrieval is silently skipped — the agent continues without memories. The Flash Memory Cache (L1) provides a high-speed fallback for recent interactions.
- **`calculate` tool uses `simpleeval` (eval RCE mitigated)**: The calculator sanitises input but does not support symbolic maths or matrix operations. Use `execute_python_script` for complex numerical workloads.

---

## 15. Future Improvements

- **Session-scoped DI container**: Refactor `container.py` to use request-scoped `AmadeusService` providers, eliminating the singleton session-ID assumption and enabling true concurrent multi-user isolation.
- **User authentication system**: Implement `/auth/register`, `/auth/login`, and `/auth/refresh` endpoints with persistent user-scoped session and memory isolation.
- **RBAC**: Add role-based access control to support multi-tenant usage with per-user tool permission profiles beyond the current binary `READ_ONLY` / `SYSTEM_FULL` split.
- **WebSocket JWT enforcement**: Move token validation to the WebSocket upgrade handshake (HTTP 101) rather than relying on downstream session checks.
- **Streaming TTS over WebSocket**: Return Edge TTS audio chunks as they are synthesised rather than buffering the entire response — reduces perceived voice latency by 40–60%.
- **`ArgumentExtractor` unit tests**: The extractor is now fully decoupled; add parametrised tests for all 15 regex fast-paths and the LLM JSON extraction flow with a mocked `LLMRouter`.
- **Mobile / browser SDK**: Thin TypeScript client library wrapping the SSE streaming and voice WebSocket endpoints.
- **Cost dashboard**: Grafana dashboard consuming the Prometheus cost gauges with daily/monthly aggregations and per-provider breakdown.

---

## 16. License

This project is licensed under the **Apache License, Version 2.0**.

See [LICENSE.txt](LICENSE.txt) for the full license text.

```
Copyright 2024 Aditya Tawde

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0
```

---

## 17. Author

**Aditya Tawde**

- GitHub: [@adityatawde9699](https://github.com/adityatawde9699)
- Repository: [github.com/adityatawde9699/Amadeus-AI](https://github.com/adityatawde9699/Amadeus-AI)
