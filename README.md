<div align="center">

# Amadeus AI

**A production-grade, multi-modal AI assistant backend built on Clean Architecture — text, voice, and tool execution unified under one API.**

[![CI Pipeline](https://github.com/adityatawde9699/Amadeus-AI/actions/workflows/main.yml/badge.svg)](https://github.com/adityatawde9699/Amadeus-AI/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.118%2B-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE.txt)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

> **Tech Stack Highlights:**
> `Python 3.11+` · `FastAPI` · `SQLAlchemy 2.0` · `Ollama` · `Groq (Llama 3.3)` · `Gemini` · `OpenAI (GPT-4o-mini)` · `Redis` · `Qdrant` · `PostgreSQL` · `JWT Auth` · `SSE Streaming` · `faster-whisper` · `Edge TTS` · `Telegram` · `WhatsApp` · `Docker` · `GitHub Actions` · `scikit-learn (TF-IDF + SVM)` · `Prometheus`

</div>

---

## 1. Problem Statement

General-purpose AI assistants are typically coupled to a single LLM provider, lack voice interoperability, and do not compose well with local system tools. When a provider's rate limit exhausts, the system fails entirely. In addition, most open-source assistants expose no structured API, have no authentication boundary, and lack mechanisms for caching repetitive queries — making them unsuitable for any deployment context beyond a single developer's machine.

---

## 2. Description / Solution

Amadeus AI is a FastAPI-based backend service that orchestrates a conversational AI agent loop across multiple LLM providers (Ollama → Groq → Gemini → OpenAI) with automatic daily quota tracking and fallback routing. It exposes REST and WebSocket endpoints for text and real-time voice interaction, executes a categorized registry of system, productivity, and informational tools, and persists conversation history in PostgreSQL or SQLite. Caching is layered over Redis to reduce redundant LLM and tool calls. All protected routes require JWT-authenticated requests.

---

## 3. Features

### Conversational AI
- Multi-LLM routing: **LlamaCpp (local GGUF)** → **Ollama (local server)** → Groq (Llama 3.3 70B) → Gemini 2.5 Flash → **OpenAI GPT-4o-mini** (emergency fallback)
- **100% Local Inference**: `SLM_MODEL_PATH` loads a GGUF model directly via `llama-cpp-python` — zero network calls, zero API cost, full conversation memory
- **Local Server Option**: `LOCAL_ONLY_MODE` via Ollama for complete offline privacy and zero-cost inference.
- **Redis-backed daily quota tracking** per provider — shared across all workers, auto-expires at midnight
- **Semantic long-term memory** via Qdrant vector search — top-3 relevant memories injected into the agent prompt on every request
- **Episodic memory (Knowledge Graph)** — LLM-driven entity extraction stores relationships (Subject-Predicate-Object) in PostgreSQL for precision context recall
- **Server-Sent Events (SSE) streaming**: `GET /api/v1/chat/stream` — native Gemini `stream=True` with word-by-word fallback for Groq
- Persistent conversation memory with configurable context window
- Concurrent request limiting (`asyncio.Semaphore` — default 20 simultaneous chats)

### Messaging & Channels
- **Inbound webhooks** — Telegram Bot API, WhatsApp Meta Cloud API (with challenge verification)
- **Outbound messaging dispatch** — `POST /api/v1/messaging/send` routes to Telegram, WhatsApp, or Email from one endpoint
- Email send/receive via SMTP (`aiosmtplib`) and IMAP (`imap_tools`)
- `GET /api/v1/messaging/status` — live readiness check for all configured channels

### Voice Interface
- Real-time bidirectional voice via WebSocket (`/api/v1/ws/voice`)
- Speech-to-text via `faster-whisper` (CTranslate2 — CPU and CUDA)
- Text-to-speech via Microsoft Edge TTS (`edge-tts`) — free, unlimited
- Configurable TTS voice (e.g. `en-US-JennyNeural`)

### Tool Execution Engine
**Information tools:**
- Current weather (OpenWeatherMap API)
- Top news headlines (NewsAPI)
- Wikipedia lookup with fallback search
- Web search via tiered SearchRouter (DuckDuckGo → Tavily)
- Date/time queries, unit conversions (temperature, length), math calculator
- Timer, greeting

**Productivity tools:**
- Task management (create, list, complete, summarize)
- Pomodoro timer (start, stop, status)
- Notes (create, list, retrieve)
- Reminders (set, list — with natural language time parsing via `dateparser`)
- **Office Integrations**: Microsoft Office adapters for creating and reading Word/Excel documents and Outlook emails (requires Windows + `pywin32`)
- **Slack Integration**: Read channels, and send or read messages via `slack-sdk`

**System & monitoring tools:**
- CPU, memory, disk, battery monitoring with configurable alert thresholds

### ML Classifier (Tool Selection)
- **TF-IDF + LinearSVC pipeline** (`scikit-learn`) — selects relevant tools locally without an LLM call
- **3,168 training examples** across **23 tool categories** — 5-fold cross-validation accuracy: **96.2%**
- Eliminates 40–60× Gemini tool-selection calls; prediction latency < 10ms vs 500ms+
- Models committed at `Model/tfidf_vectorizer.joblib` + `Model/svm_classifier.joblib`
- **CI auto-retraining**: `train-model` GitHub Actions job triggers on `data/training_data.json` changes
- Classifier status exposed in `/api/v1/health/detailed` → `classifier_enabled: true/false`

### API & Security
- **Permission Profiles**: Supports `READ_ONLY` and `SYSTEM_FULL` JWT claims to explicitly block destructive tool executions on unprivileged accounts.
- **Human-in-the-Loop (HITL) Validation**: Destructive or communicative actions pause agent execution, providing detailed **Action Previews** before waiting for human approval.
- **Isolated Filesystem Sandbox**: File operations restrict LLM execution strictly to `data/agent_workspace`, preventing path traversal vulnerabilities.
- **Agent Queue Backpressure**: The orchestrator enforces strict concurrency limits via `maxsize`, safely shedding excess loads with `HTTP 429` (Too Many Requests).
- **IPC Authentication**: Background RPC calls require an `X-IPC-Token` to prevent unauthenticated local access loops.
- JWT Bearer authentication on all protected routes (`/chat`, `/tasks`, `/voice`, `/messaging`)
- Per-user JWT rate limiting (`slowapi`) with Redis storage + IP fallback for unauthenticated requests
- **OWASP-hardened logs** — no API keys, no raw user prompts, no auth tokens in any log statement
- Request audit logging middleware (unique request IDs, latency headers, client IP)
- **Bandit security scan**: 0 HIGH severity findings in CI — enforced as gate
- **pip-audit**: 0 actionable HIGH CVEs (1 known false positive for `ecdsa` permanently ignored)
- Prometheus metrics endpoint (`/api/v1/metrics`)
- Sentry error tracking integration

### Caching (Redis)
- LLM responses: 1-hour TTL — deduplicates identical prompts
- **LLM daily usage quotas**: `llm_usage:{provider}:{date}` — 86400s TTL, shared across workers
- TTS audio: 24-hour TTL — common phrases reuse synthesized audio bytes
- Tool results (stateless only): 5-minute TTL (weather, system stats)
- Web search results: 30-minute TTL (DDG, Tavily)
- Graceful fallback if Redis is unavailable

### Observability (Prometheus — `/api/v1/metrics`)

| Metric | Type | Description |
|--------|------|-------------|
| `amadeus_llm_calls_total{provider}` | Counter | Total LLM calls per provider |
| `amadeus_tool_calls_total{tool_name}` | Counter | Per-tool invocation count |
| `amadeus_cache_hit_rate` | Gauge | Cache hit % (updated on every cache hit) |
| `amadeus_llm_cost_usd` | Gauge | Estimated LLM spend in USD |
| HTTP latency histograms | Histogram | P50/P95/P99 per route via `prometheus-fastapi-instrumentator` |

### CI/CD & Deployment
- GitHub Actions pipeline: lint (ruff — 100% clean), format check, strict type check (mypy), bandit (0 HIGH gate), pip-audit
- Automated test run with real PostgreSQL + Redis service containers
- **`train-model` CI job**: auto-retrains the ML classifier when `data/training_data.json` changes and commits updated model artifacts back to the repo
- **Coverage threshold: 80%** enforced in both CI (`--cov-fail-under=80`) and locally via `pyproject.toml`
- Staging deploy to Railway on `develop` branch merge

---

## 4. System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Python | 3.11 | 3.12 |
| RAM | 1 GB | 2 GB |
| Disk | 2 GB (with Whisper `small` model ~460 MB) | 4 GB |
| CPU | Any x86-64 | Multi-core for concurrent requests |
| GPU | Not required | CUDA-compatible for faster Whisper inference |
| OS | Linux / macOS / Windows | Linux (production) |

**External service requirements:**
- PostgreSQL 15+ (production) or SQLite (development, default)
- Redis 5+ (caching and rate limiting)

---

## 5. Setup & Installation

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
| `SECRET_KEY` | JWT signing secret — generate with `openssl rand -hex 32` |
| `GROQ_API_KEY` | Groq API key — [console.groq.com](https://console.groq.com) (free tier: 14,400 req/day) |
| `GEMINI_API_KEY` | Google Gemini key — [makersuite.google.com](https://makersuite.google.com/app/apikey) |
| `DATABASE_URL` | Database connection string (defaults to SQLite for dev) |

**Optional variables:**

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | Emergency fallback LLM (GPT-4o-mini, paid) |
| `OPENAI_MODEL` | OpenAI model override (default: `gpt-4o-mini`) |
| `REDIS_URL` | Redis for caching + quota tracking (default: `redis://localhost:6379/0`) |
| `WEATHER_API_KEY` | OpenWeatherMap API key |
| `NEWS_API_KEY` | NewsAPI key |

| `TAVILY_API_KEY` | Tavily deep search |
| `EDGE_TTS_VOICE` | Edge TTS voice name (default: `en-US-JennyNeural`) |
| `SENTRY_DSN` | Sentry error tracking DSN |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token — required for Telegram channel |
| `TELEGRAM_WEBHOOK_SECRET` | Secret header for Telegram webhook validation |
| `WHATSAPP_ACCESS_TOKEN` | Meta WhatsApp Cloud API access token |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp sender phone number ID |
| `WHATSAPP_VERIFY_TOKEN` | Token for Meta webhook challenge verification |
| `EMAIL_IMAP_SERVER` | IMAP server hostname (e.g. `imap.gmail.com`) |
| `EMAIL_SMTP_SERVER` | SMTP server hostname (e.g. `smtp.gmail.com`) |
| `EMAIL_SMTP_PORT` | SMTP port (default: `587`) |
| `EMAIL_ADDRESS` | Sender email address |
| `EMAIL_APP_PASSWORD` | Email app password (Gmail: generate in Account settings) |
| `QDRANT_URL` | Qdrant server URL for semantic memory (e.g. `http://localhost:6333`) |
| `ENV` | `development` / `staging` / `production` |

### Option A — Local Installation (without Docker)

```bash
# Install all dependencies including dev tools and voice extras
pip install -e ".[all]"

# OR using uv (faster)
uv sync --all-extras --dev

# Run database migrations
python -m alembic upgrade head

# Start the API server
uvicorn src.api.server:app --reload --host 0.0.0.0 --port 8000
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

## 6. API Documentation

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
| `POST` | `/api/v1/messaging/send` | Yes | Send outbound message (Telegram / WhatsApp / Email) |
| `GET` | `/api/v1/messaging/status` | No | Check which channels are configured |
| `POST` | `/api/v1/webhooks/telegram` | Secret token | Receive inbound Telegram updates |
| `GET` | `/api/v1/webhooks/whatsapp` | Verify token | Meta webhook challenge verification |
| `POST` | `/api/v1/webhooks/whatsapp` | — | Receive inbound WhatsApp messages |

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

## 7. Full Tech Stack

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
- **Ollama** — Default primary local LLM execution (recommended: `phi3:mini` or `llama3.2`) for offline inference
- **Groq API (Llama 3.3 70B)** — Cloud primary LLM (free tier)
- **Google Generative AI (Gemini 2.5 Flash)** — Secondary cloud LLM, supports native `stream=True`
- **OpenAI GPT-4o-mini** — Emergency fallback (paid, optional) via `openai_adapter.py`
- **Qdrant** — vector database for semantic long-term memory
- **Knowledge Graph** — structured entity relationship storage via SQLAlchemy/PostgreSQL
- **LLMRouter** — Redis-backed daily-quota-aware routing engine with atomic `INCR`/`EXPIRE`

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

---

## 8. System Architecture

### Clean Architecture — Layer Overview

```mermaid
block-beta
  columns 1

  block:clients["🌐  CLIENT LAYER"]:1
    columns 3
    A["🖥️ HTTP / REST\nclients"] B["🎙️ WebSocket\nvoice stream"] C["📨 Telegram /\nWhatsApp / Email"]
  end

  space

  block:api["⚡  API LAYER  —  src/api/"]:1
    columns 3
    D["🔐 JWT Auth\n& RBAC"] E["🛡️ Rate Limiter\nSlowAPI"] F["📋 Audit Logger\nRequest IDs"]
    G["/chat  /tasks\n/voice  /llm"] H["/webhooks\n/messaging"] I["WS /ws/voice\nSSE stream"]
  end

  space

  block:app["🧠  APPLICATION LAYER  —  src/app/"]:1
    columns 3
    J["🤖 AmadeusService\nOrchestrator"] K["🔧 ToolRegistry\nML Classifier"] L["🎤 VoiceService\nSTT → LLM → TTS"]
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
      Q["LlamaCpp  (local)"] R["Ollama  (local)"] S["Groq / Gemini / OpenAI"]
    end
    block:datablock["💾 Data"]:1
      columns 1
      T["PostgreSQL / SQLite"] U["Redis Cache"] V["Qdrant Vectors"]
    end
    block:svcblock["🛠️ Services"]:1
      columns 1
      W["Whisper STT\nEdge TTS"] X["DDG→Tavily\nSearch Router"] Y["Tools: info /\nproductivity / system"]
    end
  end

  clients --> api
  api --> app
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
    participant Ollama as 🦙 Ollama
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
        Amadeus->>Classifier: predict_intent(message)
        Classifier-->>Amadeus: tool_name (< 10ms)
        Amadeus->>Agent: run_agent_loop()
        Agent->>Router: generate(prompt, context)
        Router->>LlamaCpp: is_available()?
        alt LlamaCpp available (LOCAL_ONLY or SLM_MODEL_PATH set)
            LlamaCpp-->>Router: ✅ Response
        else LlamaCpp not configured
            Router->>Ollama: is_available()?
            alt Ollama running
                Ollama-->>Router: ✅ Response
            else Quota / Unavailable
                Router->>Groq: generate()
                Groq-->>Router: ✅ Response
            end
        end
        Router-->>Agent: (response, provider_used)
        Agent-->>Amadeus: final_response
        Amadeus->>Cache: Store response (1h TTL)
        Amadeus->>DB: Persist conversation history
    end
    Amadeus-->>FastAPI: ChatResponse
    FastAPI-->>Client: 200 JSON
```

### Voice Pipeline

```mermaid
flowchart LR
    A(["🎙️ Audio\nBytes"]):::input
    B(["📝 Transcribed\nText"]):::step
    C(["🧠 LLM\nResponse"]):::step
    D(["🔊 TTS\nAudio"]):::output

    A -->|"faster-whisper\nCPU / CUDA"| B
    B -->|"LLMRouter\nlocal-first"| C
    C -->|"Edge TTS\nen-US-JennyNeural"| D

    subgraph ws ["WebSocket  /api/v1/ws/voice"]
        B
        C
    end

    classDef input  fill:#E1F5EE,stroke:#1D9E75,color:#04342C,rx:8
    classDef step   fill:#EEEDFE,stroke:#7F77DD,color:#26215C,rx:8
    classDef output fill:#FAEEDA,stroke:#BA7517,color:#412402,rx:8
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
    <code style="background:#c5edd9;border:1px solid #9FE1CB;border-radius:4px;padding:2px 8px;font-size:12px;color:#085041;margin:2px 4px 2px 0;display:inline-block">AmadeusService</code>
    <code style="background:#c5edd9;border:1px solid #9FE1CB;border-radius:4px;padding:2px 8px;font-size:12px;color:#085041;margin:2px 4px 2px 0;display:inline-block">ML Classifier</code>
    <code style="background:#c5edd9;border:1px solid #9FE1CB;border-radius:4px;padding:2px 8px;font-size:12px;color:#085041;margin:2px 4px 2px 0;display:inline-block">ToolRegistry</code>
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
      <tr><td><strong style="font-size:12px;color:#173404">Qdrant</strong><br><span style="font-size:10px;color:#3B6D11">vector DB</span></td></tr>
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

## 9. Usage Examples

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

## 10. Project Structure

<details>
<summary><strong>Expand full tree</strong></summary>

```
Amadeus-AI/
│
├── .github/
│   ├── workflows/
│   │   └── main.yml                  # CI/CD: lint → test → train-model → deploy (Railway staging)
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md             # Structured bug report form
│   │   └── feature_request.md        # Feature request form
│   ├── PULL_REQUEST_TEMPLATE.md      # PR checklist for contributors
│   └── CODEOWNERS                    # Auto-assign reviewers by file path
├── CONTRIBUTING.md                   # Developer setup, coding standards, PR workflow
├── CHANGELOG.md                      # Release history (Keep a Changelog format)
├── SECURITY.md                       # Vulnerability reporting policy
├── CODE_OF_CONDUCT.md                # Contributor Covenant v2.1
│
├── alembic/                      # Database migration scripts
│   ├── env.py
│   └── versions/
│
├── data/
│   ├── agent_workspace/          # Sandboxed LLM filesystem (path-traversal protected)
│   ├── training_data.json        # 3 168 labeled examples across 23 tool categories
│   └── amadeus.db                # SQLite database (development only)
│
├── Model/
│   ├── tfidf_vectorizer.joblib   # TF-IDF feature extractor (trained artifact)
│   └── svm_classifier.joblib     # LinearSVC tool classifier — 96.2% CV accuracy
│
├── scripts/
│   ├── generate_training_data.py # Generates training_data.json from templates
│   └── train_classifier.py       # Trains and saves joblib model artifacts
│
├── src/
│   ├── container.py              # IoC container — wires all dependencies (dependency-injector)
│   │
│   ├── api/                      # ── API LAYER ──────────────────────────────────────────
│   │   ├── server.py             #    FastAPI app factory, middleware registration, lifespan
│   │   ├── middleware/
│   │   │   ├── authentication.py #    JWT Bearer token verification (HS256)
│   │   │   ├── rbac.py           #    READ_ONLY / SYSTEM_FULL permission profiles
│   │   │   └── audit_logger.py   #    Request ID injection, latency headers, client IP log
│   │   └── routes/
│   │       ├── chat.py           #    POST /chat · GET /chat/stream (SSE) · /history · /tools
│   │       ├── messaging.py      #    POST /messaging/send · GET /messaging/status
│   │       ├── webhooks.py       #    Telegram + WhatsApp inbound webhooks
│   │       ├── voice.py          #    WS  /ws/voice  (real-time bidirectional)
│   │       ├── tasks.py          #    CRUD /tasks
│   │       ├── health.py         #    GET /health/detailed  (DB · Redis · classifier status)
│   │       └── llm.py            #    GET /llm/usage  (daily quota report)
│   │
│   ├── app/                      # ── APPLICATION LAYER ──────────────────────────────────
│   │   └── services/
│   │       ├── amadeus_service.py #   Main orchestrator — routes request → agent / voice
│   │       ├── agent_loop.py      #   LLM ↔ tool loop with memory injection
│   │       ├── tool_registry.py   #   Tool discovery, ML classification, dispatch
│   │       └── voice_service.py   #   STT → LLM → TTS pipeline
│   │
│   ├── core/                     # ── CORE LAYER (no external deps) ──────────────────────
│   │   ├── config.py             #    Pydantic-settings: typed env var schema
│   │   ├── exceptions.py         #    AmadeusError hierarchy (→ HTTP 400 / 503)
│   │   ├── domain/
│   │   │   └── models.py         #    Pydantic domain models (ChatRequest, Task, etc.)
│   │   └── interfaces/
│   │       ├── llm.py            #    LLMAdapter ABC — all adapters must implement this
│   │       └── repositories.py   #    Abstract repository interfaces (ABCs)
│   │
│   └── infra/                    # ── INFRASTRUCTURE LAYER ────────────────────────────────
│       ├── llm/
│       │   ├── router.py             #    Multi-LLM routing + Redis quota tracking (INCR/EXPIRE)
│       │   ├── llama_cpp_adapter.py  #    LlamaCpp — local GGUF offline inference (PRIMARY)
│       │   ├── ollama_adapter.py     #    Ollama — local server inference (SECONDARY)
│       │   ├── groq_adapter.py       #    Groq — Llama 3.3 70B cloud (free tier)
│       │   ├── gemini_adapter.py     #    Gemini 2.5 Flash — supports native stream=True
│       │   ├── openai_adapter.py     #    GPT-4o-mini — emergency paid fallback
│       │   └── memory_manager.py     #    Qdrant semantic memory + Knowledge Graph (SPO)
│       ├── messaging/
│       │   ├── telegram_adapter.py  # Telegram Bot API — send + parse inbound
│       │   ├── whatsapp_adapter.py  # Meta WhatsApp Cloud API — challenge + messages
│       │   └── email_adapter.py     # SMTP (aiosmtplib) send + IMAP (imap_tools) fetch
│       ├── cache/
│       │   └── cache_service.py  #    Redis async client — LLM / TTS / tool / search TTLs
│       ├── persistence/
│       │   ├── database.py       #    Async engine + session factory (asyncpg / aiosqlite)
│       │   ├── orm_models.py     #    SQLAlchemy ORM models
│       │   └── repositories/     #    Concrete repository implementations
│       ├── speech/
│       │   ├── adapters.py       #    faster-whisper STT + pyttsx3 TTS adapters
│       │   ├── edge_tts_adapter.py #  Microsoft Edge TTS (free, unlimited)
│       │   └── tts_router.py     #    TTS provider selector
│       ├── search/
│       │   └── search_router.py  #    Tiered web search: DuckDuckGo → Tavily
│       └── tools/
│           ├── base.py           #    Tool, ToolCategory, @tool decorator
│           ├── info_tools.py     #    Weather · news · Wikipedia · calculator · search
│           ├── productivity_tools.py # Tasks · Pomodoro · notes · reminders · Slack · Office
│           ├── monitor_tools.py  #    CPU · memory · disk · battery with alert thresholds
│           └── system_tools.py   #    File ops · app launch · system commands (sandboxed)
│
├── tests/
│   ├── conftest.py               # Pytest fixtures — async DB session, DI container
│   ├── unit/
│   │   ├── test_classifier_loading.py
│   │   ├── test_openai_adapter.py
│   │   └── test_memory_agent_integration.py
│   └── integration/
│       └── test_llm_routing_fallback.py  # testcontainers PostgreSQL
│
├── Dockerfile                    # 3-stage: builder → model_cache (Whisper) → runtime
├── docker-compose.yml            # dev profile (API + PostgreSQL) + prod profile (gunicorn)
├── locustfile.py                 # Load testing configuration
├── pyproject.toml                # Project metadata, dependencies, ruff/mypy/coverage config
├── alembic.ini                   # Alembic migration configuration
└── .env.example                  # All environment variables documented with defaults
```

</details>

**Layer responsibilities at a glance:**

| Layer | Path | Responsibility |
|-------|------|----------------|
| API | `src/api/` | HTTP routing, auth middleware, request/response serialization |
| Application | `src/app/` | Orchestration, agent loop, tool dispatch, voice pipeline |
| Core | `src/core/` | Domain models, interfaces, config, exceptions — zero external deps |
| Infrastructure | `src/infra/` | LLM adapters, DB, cache, speech, search, messaging |
| Data | — | PostgreSQL · SQLite · Redis · Qdrant |

---

## 11. Testing

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

## 12. Deployment Instructions

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

### Deploy with Docker Compose (Self-hosted)

```bash
# Production profile (4 Gunicorn workers, resource limits)
docker-compose --profile prod up -d

# View logs
docker-compose logs -f api-prod

# Run migrations manually
docker-compose exec api-prod python -m alembic upgrade head
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

## 13. Known Limitations

- **No user registration or RBAC**: JWT tokens must be generated externally. There is no `/register` or `/login` endpoint. All authenticated users share the same assistant context unless `session_id` is explicitly scoped.
- **Voice WebSocket — no auth on upgrade**: WebSocket JWT enforcement depends on the client handshake; the current server accepts connections and errors downstream if the token is missing.
- **Local TTS/STT resource usage**: Running `faster-whisper` (`small` model) and Edge TTS simultaneously on a single CPU core may cause response latency of 1–5 seconds per voice round-trip.
- **Semantic memory — Qdrant must be running**: If `QDRANT_URL` is not configured or Qdrant is unreachable, memory retrieval is silently skipped — the agent continues without memories.

---

## 14. Future Improvements

- **User authentication system**: Implement `/auth/register`, `/auth/login`, and `/auth/refresh` endpoints with persistent user-scoped session isolation.
- **RBAC**: Add role-based access control to support multi-tenant usage with per-user tool restrictions.
- **WebSocket JWT enforcement**: Move token validation to the WebSocket upgrade handshake rather than relying on downstream checks.
- **Voice streaming**: Support streaming TTS back over the WebSocket as audio chunks arrive (rather than waiting for the full synthesis).
- **Mobile / browser SDK**: Thin client library for the SSE streaming and voice WebSocket endpoints.
- **Fine-tuned classifier**: Replace the TF-IDF + SVM pipeline with a fine-tuned sentence-transformer model for even higher accuracy on ambiguous multi-intent queries.
- **Cost dashboard**: Dedicated Grafana dashboard for the Prometheus cost gauges with daily/monthly aggregations.

---

## 15. License

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

## 16. Author

**Aditya Tawde**

- GitHub: [@adityatawde9699](https://github.com/adityatawde9699)
- Repository: [github.com/adityatawde9699/Amadeus-AI](https://github.com/adityatawde9699/Amadeus-AI)
