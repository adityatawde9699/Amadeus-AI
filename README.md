# Amadeus AI

A modular voice-enabled AI assistant built with Python, using Google Gemini for natural language processing and Clean Architecture principles for maintainability.

## Project Overview

Amadeus is a local-first AI assistant that combines speech recognition, natural language understanding, and system automation into a unified interface. The project provides voice and text interaction modes, persists user data locally via SQLite, and exposes functionality through both a CLI and REST API.

The architecture separates concerns into domain models, application services, infrastructure adapters, and an API layer. Tool selection uses a local TF-IDF + SVM classifier to reduce Gemini API quota consumption by predicting relevant tools before sending requests.

**Current Status**: Development/Beta. The core conversation loop, tool execution, and persistence layers are functional. Voice features require platform-specific dependencies.

## Features

### Implemented

**Conversational AI**
- Multi-turn conversation with context retention (configurable history depth)
- Google Gemini 2.0 integration for response generation
- Local ML classifier for tool prediction (reduces API calls)

**Voice Interface**
- Speech-to-text via Faster-Whisper (with fallback if unavailable)
- Text-to-speech via pyttsx3
- Wake word detection (configurable)

**Productivity Tools**
- Task management: create, list, complete, delete tasks
- Note-taking with tag support
- Reminder scheduling with natural language time parsing

**System Control**
- Application launcher (Windows, macOS, Linux support)
- File operations: search, read, copy, move, delete
- Process management: list and terminate processes
- Directory operations: create folders, list contents

**System Monitoring**
- CPU, memory, disk usage metrics
- Battery status and network statistics
- GPU monitoring (when available)
- Configurable alert thresholds

**Information Services**
- Weather data via OpenWeatherMap API
- News headlines via NewsAPI
- Wikipedia article summaries
- Basic calculations and unit conversions
- Date/time queries

**REST API**
- FastAPI-based HTTP endpoints
- Task, note, reminder CRUD operations
- Chat endpoint for programmatic access
- Health check endpoints

**Dashboard (Optional)**
- Streamlit-based web interface
- Voice input via browser
- Visual task and reminder management

### Experimental / Partial

- Pomodoro timer (implemented but limited testing)
- Calendar integration (basic structure exists)
- Docker deployment (Dockerfile present, not production-tested)

## Tech Stack

### Runtime

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| LLM | Google Gemini (google-generativeai) |
| Web Framework | FastAPI + Uvicorn |
| Database | SQLAlchemy 2.0 + SQLite (async via aiosqlite) |
| Speech Recognition | Faster-Whisper |
| Text-to-Speech | pyttsx3 |
| Validation | Pydantic + pydantic-settings |
| System Monitoring | psutil |
| Dashboard | Streamlit (optional) |

### Development

| Tool | Purpose |
|------|---------|
| pytest | Testing framework |
| Black | Code formatting |
| Ruff | Linting |
| mypy | Static type checking |
| Alembic | Database migrations |

## Architecture

The project follows Clean Architecture with four main layers:

```
┌─────────────────────────────────────────────────────────────┐
│                         API Layer                           │
│                   (FastAPI routes, middleware)              │
├─────────────────────────────────────────────────────────────┤
│                    Application Layer                        │
│           (AmadeusService, ToolRegistry, VoiceService)      │
├─────────────────────────────────────────────────────────────┤
│                       Core Layer                            │
│         (Domain models, interfaces, configuration)          │
├─────────────────────────────────────────────────────────────┤
│                   Infrastructure Layer                      │
│     (Persistence, LLM adapters, Speech adapters, Tools)     │
└─────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Location | Responsibility |
|-----------|----------|----------------|
| `core/config.py` | src/core | Centralized settings via pydantic-settings |
| `core/domain/models.py` | src/core | Pydantic models for Task, Note, Reminder, etc. |
| `app/services/amadeus_service.py` | src/app | Main orchestrator with conversation management |
| `app/services/tool_registry.py` | src/app | Tool registration and lookup |
| `infra/tools/` | src/infra | Tool implementations (productivity, system, info, monitor) |
| `infra/persistence/` | src/infra | SQLAlchemy ORM models and repositories |
| `infra/speech/` | src/infra | STT/TTS adapters |
| `api/server.py` | src/api | FastAPI application with lifespan management |
| `api/routes/` | src/api | HTTP endpoint handlers |

### Data Flow

```
User Input (Voice/Text)
        │
        ▼
┌─────────────────────┐
│   AmadeusService    │
│  ┌───────────────┐  │
│  │ ML Classifier │──┼──▶ Predict relevant tools (local)
│  └───────────────┘  │
│          │          │
│          ▼          │
│  ┌───────────────┐  │
│  │ Gemini API    │──┼──▶ Generate response / select tool
│  └───────────────┘  │
│          │          │
│          ▼          │
│  ┌───────────────┐  │
│  │ ToolExecutor  │──┼──▶ Execute selected tool
│  └───────────────┘  │
└─────────────────────┘
        │
        ▼
   SQLite Database (tasks, notes, reminders, conversations)
```

## Setup & Installation

### Prerequisites

- Python 3.11 or higher
- pip package manager
- Working microphone (for voice features)
- Internet connection (for Gemini, weather, news APIs)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/adityatawde9699/Amadeus-AI.git
   cd Amadeus-AI
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   
   # Windows
   venv\Scripts\activate
   
   # macOS/Linux
   source venv/bin/activate
   ```

3. **Install dependencies**
   
   Basic installation:
   ```bash
   pip install -r requirements.txt
   ```
   
   Or with optional features:
   ```bash
   pip install -e ".[voice,dashboard,dev]"
   ```

4. **Configure environment**
   
   Copy the example configuration:
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` and add your API keys:
   ```env
   GEMINI_API_KEY=your_gemini_api_key
   WEATHER_API_KEY=your_openweathermap_key    # optional
   NEWS_API_KEY=your_newsapi_key              # optional
   ```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | Yes | — | Google Gemini API key |
| `WEATHER_API_KEY` | No | — | OpenWeatherMap API key |
| `NEWS_API_KEY` | No | — | NewsAPI key |
| `DATABASE_URL` | No | `sqlite:///./data/amadeus.db` | Database connection string |
| `VOICE_ENABLED` | No | `true` | Enable/disable voice features |
| `WHISPER_MODEL` | No | `tiny` | Whisper model size |
| `WHISPER_DEVICE` | No | `cpu` | Device for Whisper inference |
| `DEBUG` | No | `true` | Enable debug mode |

See `.env.example` for the complete list of configuration options.

## Usage

### Run the API Server

```bash
# Using uvicorn directly
uvicorn src.api.server:app --reload --port 8000

# Or using the module
python -m src.api.server
```

The API will be available at `http://localhost:8000`. Interactive documentation is at `/docs` when `DEBUG=true`.

### API Examples

**Send a chat message:**
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What time is it?"}'
```

**Create a task:**
```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{"content": "Review pull requests"}'
```

**List tasks:**
```bash
curl http://localhost:8000/api/v1/tasks
```

**Check system health:**
```bash
curl http://localhost:8000/health
```

### Run the Dashboard (Optional)

```bash
streamlit run Amadeus/dashboard.py
```

### Legacy CLI Mode

The `Amadeus/` directory contains the original monolithic implementation:
```bash
python Amadeus/main.py           # Voice mode
python Amadeus/main.py --debug   # Text-only mode
```

## Project Structure

```
Amadeus-AI/
├── src/                          # Clean Architecture implementation
│   ├── api/                      # HTTP layer
│   │   ├── routes/               # Endpoint handlers
│   │   │   ├── chat.py           # Chat endpoints
│   │   │   ├── tasks.py          # Task CRUD
│   │   │   ├── health.py         # System health
│   │   │   └── voice.py          # TTS endpoints
│   │   └── server.py             # FastAPI app
│   ├── app/                      # Application layer
│   │   └── services/
│   │       ├── amadeus_service.py # Main orchestrator
│   │       ├── tool_registry.py   # Tool management
│   │       └── voice_service.py   # Voice coordination
│   ├── core/                     # Domain layer
│   │   ├── config.py             # Settings management
│   │   ├── domain/models.py      # Domain entities
│   │   ├── exceptions.py         # Custom exceptions
│   │   └── interfaces/           # Abstract interfaces
│   └── infra/                    # Infrastructure layer
│       ├── llm/                  # LLM adapters
│       ├── persistence/          # Database (SQLAlchemy)
│       ├── speech/               # STT/TTS adapters
│       └── tools/                # Tool implementations
│           ├── base.py           # Tool decorator and executor
│           ├── productivity_tools.py
│           ├── system_tools.py
│           ├── monitor_tools.py
│           └── info_tools.py
├── Amadeus/                      # Legacy monolithic implementation
├── tests/                        # Test suite
│   ├── unit/
│   └── integration/
├── data/                         # SQLite database storage
├── requirements.txt              # Minimal dependencies
├── pyproject.toml                # Full project configuration
├── Dockerfile                    # Container definition
└── docker-compose.yml            # Multi-container setup
```

## Known Limitations

**Voice Features**
- Faster-Whisper requires additional system dependencies (PortAudio, Rust). Falls back to mock input if unavailable.
- TTS quality varies by platform (pyttsx3 uses system voices).
- No real-time voice activity detection; uses fixed timeout.

**Tool Execution**
- File operations are limited to user-accessible paths.
- Application launcher mappings are hardcoded for common apps.
- No sandboxing for tool execution.

**Database**
- Default SQLite limits concurrent write operations.
- No automatic backup mechanism.

**Authentication**
- No authentication implemented. The API should not be exposed publicly without adding auth middleware.

**API Rate Limiting**
- Rate limiting configuration exists but is not enforced by default.

**Testing**
- Integration tests require API keys to run.
- Coverage target is 70% but not currently met.

## Future Improvements

1. **Authentication Layer**: Implement JWT or API key authentication for the REST API.

2. **Plugin System**: Replace hardcoded tool registration with a plugin discovery mechanism.

3. **Voice Activity Detection**: Add VAD to replace fixed timeout-based speech recognition.

4. **Persistent Conversations**: Add session management for multi-session conversation history.

5. **GPU Acceleration**: Improve Whisper performance with CUDA support configuration.

6. **PostgreSQL Support**: Test and document async PostgreSQL setup for production deployments.

7. **Tool Sandboxing**: Add process isolation for file and system tools.

8. **Streaming Responses**: Implement SSE for streaming LLM responses to the API.

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run only unit tests
pytest tests/unit/

# Run only integration tests (requires API keys)
pytest tests/integration/
```

## License

Apache License 2.0 — see [LICENSE.txt](LICENSE.txt) for details.

## Acknowledgments

- [Google Gemini](https://ai.google.dev/) — Language model
- [Faster-Whisper](https://github.com/guillaumekln/faster-whisper) — Speech recognition
- [FastAPI](https://fastapi.tiangolo.com/) — Web framework
- [SQLAlchemy](https://www.sqlalchemy.org/) — Database ORM
- [pyttsx3](https://github.com/nateshmbhat/pyttsx3) — Text-to-speech

---

**Author**: Aditya S. Tawde
