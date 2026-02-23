<div align="center">

# Amadeus AI

**A production-grade, multi-modal AI assistant backend built on Clean Architecture — text, voice, and tool execution unified under one API.**

[![CI Pipeline](https://github.com/adityatawde9699/Amadeus-AI/actions/workflows/main.yml/badge.svg)](https://github.com/adityatawde9699/Amadeus-AI/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.118%2B-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE.txt)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

> **Tech Stack Highlights:**
> `Python 3.11` · `FastAPI` · `SQLAlchemy` · `Gemini` · `Groq (Llama 3.3)` · `Redis` · `PostgreSQL` · `JWT Auth` · `faster-whisper` · `Edge TTS` · `Docker` · `GitHub Actions`

</div>

---

## 1. Problem Statement

General-purpose AI assistants are typically coupled to a single LLM provider, lack voice interoperability, and do not compose well with local system tools. When a provider's rate limit exhausts, the system fails entirely. In addition, most open-source assistants expose no structured API, have no authentication boundary, and lack mechanisms for caching repetitive queries — making them unsuitable for any deployment context beyond a single developer's machine.

---

## 2. Description / Solution

Amadeus AI is a FastAPI-based backend service that orchestrates a conversational AI agent loop across multiple LLM providers (Groq → Gemini → OpenAI) with automatic daily quota tracking and fallback routing. It exposes REST and WebSocket endpoints for text and real-time voice interaction, executes a categorized registry of system, productivity, and informational tools, and persists conversation history in PostgreSQL or SQLite. Caching is layered over Redis to reduce redundant LLM and tool calls. All protected routes require JWT-authenticated requests.

---

## 3. Features

### Conversational AI
- Multi-LLM routing: Groq (Llama 3.3 70B) as primary → Gemini 2.5 Flash → OpenAI (high-complexity fallback)
- Daily quota tracking per provider with automatic midnight reset
- Persistent conversation memory with configurable context window
- Semantic (long-term) memory via ChromaDB vector embeddings *(experimental)*

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
- Web search via tiered SearchRouter (DuckDuckGo → Brave → Tavily)
- Date/time queries, unit conversions (temperature, length), math calculator
- Timer, greeting

**Productivity tools:**
- Task management (create, list, complete, summarize)
- Pomodoro timer (start, stop, status)
- Notes (create, list, retrieve)
- Reminders (set, list — with natural language time parsing via `dateparser`)

**System & monitoring tools:**
- CPU, memory, disk, battery monitoring with configurable alert thresholds

### API & Security
- JWT Bearer authentication on all protected routes (`/chat`, `/tasks`, `/voice`)
- SlowAPI rate limiting (configurable, default 60 req/min per IP)
- Request audit logging middleware (request IDs, latency headers)
- Prometheus metrics endpoint (`/api/v1/metrics`)
- Sentry error tracking integration

### Caching (Redis)
- LLM responses: 1-hour TTL
- TTS audio: 24-hour TTL
- Tool results (stateless only): 5-minute TTL
- Web search results: 30-minute TTL
- Graceful fallback if Redis is unavailable

### CI/CD & Deployment
- GitHub Actions pipeline: lint (ruff), format check, type check (mypy), security scan (bandit), dependency audit (pip-audit)
- Automated test run with real PostgreSQL service container
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
| `OPENAI_API_KEY` | Emergency fallback LLM (paid) |
| `REDIS_URL` | Redis for caching (default: `redis://localhost:6379/0`) |
| `WEATHER_API_KEY` | OpenWeatherMap API key |
| `NEWS_API_KEY` | NewsAPI key |
| `BRAVE_SEARCH_API_KEY` | Brave Search (2,000 free/month) |
| `TAVILY_API_KEY` | Tavily deep search |
| `EDGE_TTS_VOICE` | Edge TTS voice name (default: `en-US-JennyNeural`) |
| `SENTRY_DSN` | Sentry error tracking DSN |
| `TELEGRAM_BOT_TOKEN` | Telegram bot integration |
| `CHROMA_ENABLED` | Enable ChromaDB vector memory (default: `true`) |
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
| `GET` | `/api/v1/chat/history` | Yes | Retrieve conversation history by session |
| `GET` | `/api/v1/chat/tools` | Yes | List all available tools by category |
| `POST` | `/api/v1/chat/clear` | Yes | Clear conversation history |

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
- **Google Generative AI (Gemini 2.5 Flash)** — secondary LLM
- **Groq API (Llama 3.3 70B)** — primary LLM (free tier)
- **OpenAI** — emergency fallback (paid, optional)
- **ChromaDB** — vector database for semantic memory *(experimental)*
- **LLMRouter** — internal daily-quota-aware routing engine

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

## 8. System Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                                 │
│          HTTP / REST Clients         WebSocket (voice stream)        │
└───────────────────────┬──────────────────────────┬───────────────────┘
                        │                          │
┌──────────────────────▼──────────────────────────▼───────────────────┐
│                         API LAYER  (src/api/)                        │
│  FastAPI routes: /chat, /tasks, /voice, /health, /llm               │
│  Middleware: JWT Auth · Audit Logger · SlowAPI Rate Limiter          │
│  Exception handlers: AmadeusError → 400, Generic → 500              │
└───────────────────────┬──────────────────────────────────────────────┘
                        │  Depends()
┌──────────────────────▼──────────────────────────────────────────────┐
│                   APPLICATION LAYER  (src/app/)                      │
│  AmadeusService → AgentLoop → ToolRegistry                          │
│  VoiceService (STT → LLM → TTS pipeline)                           │
└────────┬──────────────────────────┬─────────────────────────────────┘
         │ Core Interfaces          │ Infrastructure Services
┌────────▼──────────────┐  ┌───────▼──────────────────────────────────┐
│  CORE LAYER (src/core)│  │        INFRA LAYER  (src/infra/)          │
│  Domain Models        │  │  ┌────────────┐  ┌──────────────────────┐│
│  Interfaces / ABCs    │  │  │ LLMRouter   │  │ CacheService (Redis) ││
│  Config (Settings)    │  │  │ Groq/Gemini │  │  llm / tts / tool   ││
│  Exceptions           │  │  │ adapters    │  │  search namespaces  ││
└───────────────────────┘  │  └────────────┘  └──────────────────────┘│
                           │  ┌────────────┐  ┌──────────────────────┐│
                           │  │ Persistence │  │  Tools               ││
                           │  │ SQLAlchemy  │  │  info / productivity ││
                           │  │ Alembic     │  │  system / monitor    ││
                           │  └────────────┘  └──────────────────────┘│
                           │  ┌────────────┐  ┌──────────────────────┐│
                           │  │ Speech      │  │ SearchRouter          ││
                           │  │ Whisper STT │  │ DDG → Brave → Tavily ││
                           │  │ Edge TTS    │  └──────────────────────┘│
                           │  └────────────┘                           │
                           └──────────────────────────────────────────┘
                                        │
┌───────────────────────────────────────▼──────────────────────────────┐
│                        DATA LAYER                                     │
│     PostgreSQL (prod)   SQLite (dev)   Redis (cache)   ChromaDB      │
└───────────────────────────────────────────────────────────────────────┘
```

**LLM Routing Order:**
```
Request → Groq (14,400/day free) → Gemini (1,500/day free) → OpenAI (100/day paid)
                                         ↓ all exhausted →
                               LLMRateLimitError (503)
```

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

### Tool Discovery

```bash
# List all available tools grouped by category
curl "http://localhost:8000/api/v1/chat/tools" \
  -H "Authorization: Bearer $TOKEN"
```

### LLM Usage Report (no auth)

```bash
curl "http://localhost:8000/api/v1/llm/usage"
# Returns: provider usage counts, daily limits, remaining quota, estimated cost
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
        audio_bytes = await ws.recv()     # binary TTS audio

asyncio.run(voice_session())
```

---

## 10. Project Structure

```
Amadeus-AI/
├── .github/
│   └── workflows/
│       └── main.yml              # CI/CD: lint, test, deploy to Railway staging
├── alembic/                      # Database migration scripts
│   ├── env.py
│   └── versions/
├── data/                         # Local data (SQLite db, ChromaDB)
├── src/
│   ├── container.py              # IoC container — wires all dependencies
│   ├── api/
│   │   ├── server.py             # FastAPI app, middleware, lifespan
│   │   ├── middleware/
│   │   │   ├── authentication.py # JWT Bearer token verification
│   │   │   └── audit_logger.py   # Request ID + timing middleware
│   │   └── routes/
│   │       ├── chat.py           # POST /chat, GET /history, GET /tools
│   │       ├── voice.py          # WebSocket /ws/voice
│   │       ├── tasks.py          # CRUD /tasks
│   │       ├── health.py         # GET /health/detailed
│   │       └── llm.py            # GET /llm/usage
│   ├── app/
│   │   └── services/
│   │       ├── amadeus_service.py # Main orchestrator
│   │       ├── agent_loop.py      # LLM ↔ tool execution loop
│   │       ├── tool_registry.py   # Tool discovery and dispatch
│   │       └── voice_service.py   # STT → LLM → TTS pipeline
│   ├── core/
│   │   ├── config.py             # Pydantic-settings: all env vars
│   │   ├── exceptions.py         # Domain exception hierarchy
│   │   ├── domain/
│   │   │   └── models.py         # Pydantic domain models
│   │   └── interfaces/
│   │       └── repositories.py   # Abstract repository interfaces
│   └── infra/
│       ├── llm/
│       │   ├── router.py         # Multi-LLM routing with daily quota tracking
│       │   ├── gemini_adapter.py # Google Gemini adapter
│       │   └── groq_adapter.py   # Groq adapter
│       ├── cache/
│       │   └── cache_service.py  # Redis cache (LLM, TTS, tool, search)
│       ├── persistence/
│       │   ├── database.py       # Engine, session factory
│       │   ├── orm_models.py     # SQLAlchemy ORM models
│       │   └── repositories/     # Concrete repository implementations
│       ├── speech/
│       │   ├── adapters.py       # Whisper STT, pyttsx3 TTS adapters
│       │   ├── edge_tts_adapter.py # Edge TTS adapter
│       │   └── tts_router.py     # TTS provider selector
│       ├── search/
│       │   └── search_router.py  # Tiered web search (DDG → Brave → Tavily)
│       └── tools/
│           ├── base.py           # Tool, ToolCategory, @tool decorator
│           ├── info_tools.py     # Weather, news, Wikipedia, calculator, etc.
│           ├── productivity_tools.py # Tasks, Pomodoro, notes, reminders
│           ├── monitor_tools.py  # CPU, memory, disk, battery monitoring
│           └── system_tools.py   # File ops, app launch, system commands
├── tests/
│   ├── conftest.py               # Pytest fixtures (async DB session, DI container)
│   └── unit/                     # Unit test modules
├── Dockerfile                    # Multi-stage build (builder → model_cache → runtime)
├── docker-compose.yml            # Development and production profiles
├── pyproject.toml                # Project metadata, dependencies, tool configs
├── alembic.ini                   # Alembic configuration
├── .env.example                  # Environment variable documentation template
└── locustfile.py                 # Load testing configuration (Locust)
```

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
# Unit tests only
pytest tests/ -m unit -v

# Integration tests (requires running PostgreSQL)
pytest tests/ -m integration -v

# Skip slow tests
pytest tests/ -m "not slow" -v
```

### Coverage Threshold

The project enforces a minimum of 40% coverage in CI (enforced via `--cov-fail-under=40` in GitHub Actions). The `pyproject.toml` locally reports `fail_under = 70` as a target.

### Integration Tests

Integration tests use `testcontainers[postgres]` to spin up a temporary PostgreSQL container. No manual database setup required:

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
# Install Railway CLI
npm install -g @railway/cli

# Login and link
railway login
railway link

# Deploy
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

The Dockerfile is a **3-stage multi-stage build**:
1. **builder** — installs Python dependencies
2. **model_cache** — pre-downloads Whisper `small` model (~460 MB) to avoid cold-start latency
3. **runtime** — minimal production image, non-root user (`amadeus`)

The container starts with:
```bash
alembic upgrade head && uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --workers 1
```

---

## 13. Known Limitations

- **No user registration or RBAC**: JWT tokens must be generated externally. There is no `/register` or `/login` endpoint. All authenticated users share the same assistant context unless `session_id` is explicitly scoped.
- **Single-instance agent loop**: The `LLMRouter` usage counters are stored in memory and reset on process restart. Running multiple workers without a shared Redis counter will cause quota tracking inconsistencies.
- **Voice WebSocket — no auth on upgrade**: WebSocket JWT enforcement is dependent on proper implementation in the client handshake; the current server accepts connections and errors downstream if token is missing.
- **ChromaDB semantic memory — experimental**: The vector memory (`CHROMA_ENABLED=true`) is not integrated into the core agent loop response pipeline. It exists as infrastructure but is not queried during inference.
- **Messaging integrations (Telegram, WhatsApp, Email) — not yet implemented**: Configuration variables exist in `.env.example` but no corresponding route or handler code was found in the scanned source.
- **OpenAI adapter**: Listed in `LLMRouter` and `.env.example` but no `openai_adapter.py` was found in `src/infra/llm/`. The fallback will log an error if triggered.
- **Test coverage below target**: GitHub Actions enforces 40% coverage. The local `pyproject.toml` sets a target of 70%, which is not currently met based on prior test run analysis.
- **Local TTS/STT resource usage**: Running `faster-whisper` (`small` model) and Edge TTS simultaneously on a single CPU core may cause response latency of 1–5 seconds per voice round-trip.

---

## 14. Future Improvements

- **OpenAI adapter implementation**: Complete the `openai_adapter.py` to enable the emergency fallback route in `LLMRouter`.
- **User authentication system**: Implement `/auth/register`, `/auth/login`, and `/auth/refresh` endpoints with user-scoped session isolation.
- **Shared quota tracking**: Move `LLMRouter` daily counters to Redis to support multi-worker production deployments correctly.
- **ChromaDB integration into agent loop**: Wire the semantic memory layer into the `AgentLoop` context-building step to enable long-term recall during inference.
- **Messaging integrations**: Implement Telegram, WhatsApp (Meta Cloud API), and email channel handlers referenced in `.env.example`.
- **Streaming LLM responses**: Replace batch LLM responses with server-sent events (SSE) or WebSocket streaming for lower time-to-first-token.
- **Improve test coverage**: Add integration tests for tool execution, LLM routing fallback behavior, and the voice pipeline to reach the 70% coverage target.
- **RBAC**: Add role-based access control to support multi-tenant usage with per-user tool restrictions.

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
- Email: adityatawde9699@gmail.com
- Repository: [github.com/adityatawde9699/Amadeus-AI](https://github.com/adityatawde9699/Amadeus-AI)


