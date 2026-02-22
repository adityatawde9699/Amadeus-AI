<div align="center">

# 🎵 Amadeus-AI

**A production-ready, omni-channel AI assistant backend built with Clean Architecture in Python.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square&logo=python)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.118%2B-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE.txt)
[![Tests](https://img.shields.io/badge/tests-38%20passing-brightgreen?style=flat-square)](tests/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?style=flat-square&logo=docker)](Dockerfile)

</div>

---

## Overview

Amadeus-AI is a backend service for a fully async, multi-channel AI assistant. It orchestrates user commands through a **Multi-LLM routing system** (Google Gemini + Groq), executes real-world tools, maintains **cross-session long-term memory** via a ChromaDB vector store, and delivers responses over REST APIs, Telegram, WhatsApp, and Email.

The codebase follows **Clean Architecture** — separating domain logic, application services, infrastructure adapters, and API presentation into strict layers.

---

## Feature Highlights

| Category | Feature |
|---|---|
| 🧠 **LLM Routing** | Gemini 2.5 Flash + Groq (Llama 3) with automatic fallback |
| 💾 **Long-Term Memory** | ChromaDB vector store + Gemini embeddings for semantic cross-session recall |
| 🛠️ **Tool Execution Engine** | 40+ callable tools covering productivity, system ops, info, and web |
| 🎙️ **Voice Interface** | Whisper (STT), Edge-TTS / ElevenLabs (TTS), wake-word detection |
| 📱 **Messaging Channels** | Telegram (python-telegram-bot v20+) · WhatsApp (Meta Cloud API) · Email (IMAP/SMTP) |
| 🔐 **Security** | JWT authentication middleware + SlowAPI rate limiting |
| 📊 **Observability** | Structlog structured logging · Sentry error tracking · Prometheus metrics |
| 🗄️ **Persistence** | Async PostgreSQL (prod) / SQLite (dev) via SQLAlchemy 2.0 + Redis cache |
| 🐳 **Containerized** | Docker + Docker Compose with dev/staging/production profiles |
| ✅ **CI/CD** | GitHub Actions pipeline: lint (Ruff, Black, Mypy) → test → build |

---

## Architecture

The backend follows a strict four-layer Clean Architecture:

```
┌─────────────────────────────────────────────────────────────────────┐
│  API Layer (FastAPI)                                                 │
│  JWT Auth · Rate Limiting · REST Routes · Webhook Receivers         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  Application Layer                                                   │
│  AmadeusService · ReActAgent (agent_loop) · ToolRegistry            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  Infrastructure Layer                                                │
│  LLM Adapters (Gemini/Groq)  ·  ChromaDB Memory                    │
│  Messaging (Telegram/WA/Email) · Speech (Whisper/Edge-TTS)         │
│  PostgreSQL/SQLite Repos · Redis Cache · Search Router (DDG/Brave)  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  Core Domain Layer                                                   │
│  Config · Interfaces · Domain Models · Custom Exceptions            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Tool Capabilities

### 📅 Productivity
- **Pomodoro Timer** — start/pause/stop work sessions with configurable cycles
- **Reminders** — natural language scheduling with background polling
- **Calendar Events** — create, list, and query upcoming events
- **Tasks/To-Do** — add, complete, and list pending tasks
- **Notes** — tagged note creation and retrieval

### ℹ️ Information & Web
- **Weather** — current conditions + feel-like via OpenWeatherMap
- **News Headlines** — category/country filtered, via NewsAPI
- **Wikipedia Search** — article summaries with fallback search
- **Web Search** — tiered router: DuckDuckGo → Brave Search → Tavily
- **Calculator** — safe expression evaluator supporting `sqrt`, `**`, `%`
- **Unit Converters** — length (mm/cm/m/km/in/ft/mi) and temperature (C/F/K)
- **Timer** — countdown timer up to 24 hours

### 🖥️ System & OS
- **System Status** — CPU, RAM, disk usage, battery, and uptime
- **Process Monitor** — list and kill running processes
- **Volume Control** — adjust system audio
- **Power Control** — shutdown / restart / sleep
- **Filesystem** — safe read, write, search, and directory navigation
- **App Launcher** — open applications by name

### 📡 Messaging (Outbound)
- **Telegram** — text + voice replies, inline keyboard buttons
- **WhatsApp** — text, interactive buttons, and template messages
- **Email** — read unread mail, compose and send replies via SMTP

---

## Long-Term Memory

Amadeus uses a **two-tier memory architecture**:

| Tier | Storage | Scope | Purpose |
|------|---------|-------|---------|
| Short-term | PostgreSQL / SQLite (`messages` table) | Per-session | Recent conversation context |
| Long-term | ChromaDB (vector DB) + Gemini embeddings | Cross-session | Semantic recall of past preferences and facts |

Every user and assistant message is embedded and stored. On each new query, the top-5 most semantically similar past messages are retrieved and injected into the LLM system prompt — enabling Amadeus to **remember things across sessions without being told twice**.

```python
# Example: tell it in session A
"My name is Aditya and I love astronomy"

# Ask in session B (different session_id, days later)
"What do I enjoy?" → Amadeus recalls "astronomy" ✅
```

>  Memory requires `GEMINI_API_KEY` and `CHROMA_ENABLED=true`. If either is missing, the service silently degrades to session-only memory.

---

## Project Structure

```
Amadeus-AI/
├── src/
│   ├── api/                    # Presentation layer (FastAPI)
│   │   ├── routes/             # chat.py, health.py, tasks.py, voice.py, webhooks.py
│   │   ├── middleware/         # JWT auth, rate limiting
│   │   └── server.py           # App factory & startup lifecycle
│   │
│   ├── app/                    # Application layer
│   │   └── services/
│   │       ├── amadeus_service.py   # Main orchestrator
│   │       ├── agent_loop.py        # ReAct multi-step agent
│   │       ├── tool_registry.py     # Tool discovery & Gemini tool spec builder
│   │       └── voice_service.py     # Voice session coordinator
│   │
│   ├── core/                   # Domain layer (no external dependencies)
│   │   ├── config.py           # Pydantic settings (all env vars)
│   │   ├── interfaces/         # Abstract repository and service interfaces
│   │   ├── domain/             # Domain models
│   │   └── exceptions.py       # Custom exceptions hierarchy
│   │
│   └── infra/                  # Infrastructure layer
│       ├── llm/
│       │   ├── router.py           # Multi-LLM routing (Gemini → Groq fallback)
│       │   ├── gemini_adapter.py   # Google Generative AI adapter
│       │   └── groq_adapter.py     # Groq API adapter
│       ├── memory_service.py       # ChromaDB long-term semantic memory
│       ├── messaging/
│       │   ├── telegram_adapter.py # python-telegram-bot v20+
│       │   ├── whatsapp_adapter.py # Meta Cloud API (buttons + templates)
│       │   └── email_adapter.py    # IMAP/SMTP email integration
│       ├── persistence/
│       │   ├── database.py         # Async SQLAlchemy engine & session
│       │   ├── orm_models.py       # All database table definitions
│       │   └── repositories/       # Concrete async repository implementations
│       ├── search/                 # Tiered web search router (DDG/Brave/Tavily)
│       ├── speech/                 # Whisper STT, Edge-TTS, ElevenLabs TTS
│       ├── cache/                  # Redis cache service
│       └── tools/                  # All executable tools
│           ├── base.py             # Tool decorator, ToolExecutor, ToolCategory
│           ├── info_tools.py       # Weather, news, Wikipedia, calculator, timer
│           ├── productivity_tools.py # Pomodoro, tasks, notes, reminders, calendar
│           ├── system_tools.py     # Volume, power, app launch, OS operations
│           ├── monitor_tools.py    # CPU/RAM/disk/process monitoring
│           ├── filesystem_tools.py # File read/write/search
│           └── email_tools.py      # Email tool wrappers
│
├── tests/
│   ├── unit/                   # Fast unit tests (mock all I/O)
│   │   ├── core/test_config.py
│   │   ├── test_memory_service.py
│   │   └── test_messaging_adapters.py
│   └── integration/            # Integration tests (testcontainers)
│
├── alembic/                    # Database migration scripts
├── data/                       # Runtime data (SQLite, ChromaDB)
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```

---

## Tech Stack

| Layer | Technology |
|------|-----------|
| **Runtime** | Python 3.11+ |
| **Web Framework** | FastAPI + Uvicorn (ASGI) |
| **LLMs** | Google Gemini 2.5 Flash, Groq (Llama 3.3 70B) |
| **Vector Memory** | ChromaDB (persistent) + Gemini `embedding-001` |
| **ORM** | SQLAlchemy 2.0 (async) |
| **Databases** | PostgreSQL (prod) · SQLite (dev) |
| **Cache / Broker** | Redis |
| **Migrations** | Alembic |
| **IoC Container** | dependency-injector |
| **Validation** | Pydantic v2 + pydantic-settings |
| **STT** | faster-whisper (local) · SpeechRecognition |
| **TTS** | Edge-TTS · ElevenLabs · pyttsx3 |
| **Messaging** | python-telegram-bot v20+ · Meta Cloud API (WhatsApp) · imap-tools / aiosmtplib |
| **Observability** | Structlog · Sentry · Prometheus (prometheus-fastapi-instrumentator) |
| **Testing** | Pytest · pytest-asyncio · testcontainers |
| **Code Quality** | Ruff · Black · Mypy |
| **CI/CD** | GitHub Actions |
| **Containers** | Docker · Docker Compose |

---

## Setup & Installation

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (recommended)
- A [Gemini API key](https://makersuite.google.com/app/apikey) — required for LLM + memory embeddings

### 1 — Clone & Configure

```bash
git clone https://github.com/adityatawde9699/Amadeus-AI.git
cd Amadeus-AI
cp .env.example .env
# Edit .env and fill in your API keys
```

### 2 — Run with Docker (Recommended)

```bash
# Development (hot-reload, SQLite + Redis in containers)
docker-compose up --build

# Production (Gunicorn workers, PostgreSQL)
docker-compose --profile prod up --build -d
```

### 3 — Run Locally (without Docker)

```bash
# Install all dependencies
pip install -e ".[all]"
# Or with uv (faster)
uv pip install -e ".[all]"

# Apply database migrations
alembic upgrade head

# Start the server
uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload
```

---

## Configuration

All settings are loaded from environment variables. Copy `.env.example` to `.env` and fill in the values.

### Required Keys

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Primary LLM + memory embeddings |
| `SECRET_KEY` | JWT signing (generate: `openssl rand -hex 32`) |

### Optional Keys (enables features)

| Variable | Feature |
|---|---|
| `GROQ_API_KEY` | Fallback LLM (free: 14,400 req/day) |
| `WEATHER_API_KEY` | Weather tool (OpenWeatherMap) |
| `NEWS_API_KEY` | News headlines tool |
| `BRAVE_SEARCH_API_KEY` | Web search (tier 2) |
| `TAVILY_API_KEY` | Deep web research (tier 3) |
| `ELEVENLABS_API_KEY` | High-quality TTS voice |
| `TELEGRAM_BOT_TOKEN` | Telegram messaging channel |
| `TELEGRAM_WEBHOOK_URL` | Telegram webhook endpoint (HTTPS) |
| `WHATSAPP_ACCESS_TOKEN` | WhatsApp messaging channel |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp sender ID |
| `WHATSAPP_VERIFY_TOKEN` | WhatsApp webhook verification |
| `EMAIL_ADDRESS` | Email integration |
| `EMAIL_APP_PASSWORD` | Email app password / OAuth token |
| `CHROMA_ENABLED` | Enable long-term vector memory (`true`/`false`) |
| `SENTRY_DSN` | Error tracking |

---

## API Reference

The server starts at `http://localhost:8000`. All protected endpoints require a JWT Bearer token.

### Chat

```bash
# Send a message
POST /api/v1/chat
Content-Type: application/json
Authorization: Bearer <JWT>

{"message": "What's the weather in Mumbai?", "source": "text"}
```

```bash
# Retrieve conversation history
GET /api/v1/chat/history?session_id=<UUID>
Authorization: Bearer <JWT>
```

```bash
# List all available tools
GET /api/v1/chat/tools
Authorization: Bearer <JWT>
```

### Tasks & Productivity

```bash
# List tasks
GET /api/v1/tasks
Authorization: Bearer <JWT>

# Create a task
POST /api/v1/tasks
{"content": "Review pull requests"}
```

### Health & Metrics

```bash
# Health check (public)
GET /health

# Readiness probe
GET /health/ready

# Prometheus metrics (public)
GET /metrics
```

### Webhooks (Messaging)

```bash
# Telegram webhook (configured via set_webhook)
POST /api/v1/messaging/telegram

# WhatsApp webhook verification (GET) + events (POST)
GET  /api/v1/messaging/whatsapp?hub.verify_token=<token>&hub.challenge=<ch>
POST /api/v1/messaging/whatsapp
```

---

## Running Tests

```bash
# All unit tests (no API keys needed — all mocked)
.venv/Scripts/python.exe -m pytest tests/unit/ -v

# Integration tests (requires Docker for testcontainers)
pytest tests/integration/ -v -m integration

# With coverage report
pytest tests/unit/ --cov=src --cov-report=term-missing
```

> ✅ **Current status**: 38 unit tests passing, 0 failures.

---

## Telegram Webhook Setup

Once deployed to a public HTTPS host (Railway, Render, etc.):

```python
from src.infra.messaging.telegram_adapter import TelegramAdapter
from src.core.config import get_settings

settings = get_settings()
adapter = TelegramAdapter()

# Run once at deploy time
await adapter.set_webhook(
    webhook_url=settings.TELEGRAM_WEBHOOK_URL,
    secret_token=settings.TELEGRAM_WEBHOOK_SECRET,
)
```

For local development, use [ngrok](https://ngrok.com/) to get a public HTTPS tunnel:

```bash
ngrok http 8000
# Then set TELEGRAM_WEBHOOK_URL=https://<ngrok-id>.ngrok.io/api/v1/messaging/telegram
```

---

## Known Limitations

- **No Frontend**: The system is a pure backend. Interaction is via raw HTTP, Telegram, WhatsApp, or Email.
- **Async Task Queue**: Long-running background jobs use basic `asyncio.sleep()` — a Celery/ARQ worker queue would be more robust for production.
- **No WebSocket Streaming**: LLM responses are returned synchronously; real-time streaming requires a WebSocket endpoint.
- **Voice Locally Intensive**: `faster-whisper` and local TTS consume significant CPU/RAM on hardware without GPU acceleration.
- **ChromaDB Not Clustered**: ChromaDB runs in-process (local persistent store). For multi-instance deployments, switch to Qdrant or Pinecone.

---

## Future Improvements

- [ ] WebSocket endpoint for streaming real-time LLM/TTS responses
- [ ] Celery / ARQ task queue for long-running background jobs
- [ ] Role-based access control (RBAC) for multi-tenant usage
- [ ] Transition ChromaDB to Qdrant for clustered, multi-instance deployments
- [ ] Discord and Slack messaging adapters
- [ ] Admin dashboard (Streamlit UI is scaffolded in optional deps)

---

## License

Distributed under the **MIT License**. See [LICENSE.txt](LICENSE.txt) for details.

---

<div align="center">
Built by <a href="https://github.com/adityatawde9699">Aditya Tawde</a> · <a href="https://github.com/adityatawde9699/Amadeus-AI/issues">Report an Issue</a>
</div>
