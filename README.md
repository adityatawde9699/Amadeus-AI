# Project Overview

Amadeus-AI is a backend service for an AI-powered voice and text assistant built using Clean Architecture principles in Python. It provides an extensible agent loop that processes user commands, manages conversation history, and invokes various system and productivity tools. The architecture strictly separates core domain models from application logic, infrastructure integrations, and API presentation, ensuring maintainability and robust dependency management.

## Features

- **Conversational AI Core**: Orchestrates input processing via a Multi-LLM Routing architecture (Google Gemini & Groq models).
- **Voice Interface**: Supports speech recognition and text-to-speech workflows (via `faster-whisper`, `pyttsx3`, and `edge-tts`).
- **Tool Execution Engine**: Dynamically executes tools across categories including system operations, productivity (Pomodoro, calendar), and monitoring.
- **Conversation Persistence**: Async SQLite and PostgreSQL support for persistent chat history.
- **Performance Caching**: Redis-backed caching layer for fast data retrieval and optimized API limits.
- **Security & Reliability**: JWT Authentication middleware and SlowAPI rate-limiting safeguard endpoints.
- **RESTful API**: Exposes endpoints for chat, tool listing, and history retrieval.
- **Observability Hooks**: Integrates Structlog, Sentry, and Prometheus.
- **CI/CD Automation**: GitHub Actions pipeline for linting, testing, and continuous integration.

## Tech Stack

**Runtime:**
- Python 3.11+
- Containerized via Docker

**Frameworks:**
- FastAPI (Web framework)
- SQLAlchemy (Async ORM)
- dependency-injector (IoC container)
- Pydantic (Validation & Settings)

**Databases:**
- PostgreSQL (Production)
- SQLite (Development)
- Redis (Caching & Message Brokering)

**APIs & Services:**
- Google Generative AI (Gemini)
- Groq API (High-speed LLM Inference)
- OpenWeatherMap API & News API integrations
- Sentry (Error tracking)

**Development:**
- Testing: Pytest, pytest-asyncio, Testcontainers
- Code Quality: Ruff, Black, Mypy
- CI/CD: GitHub Actions

## Architecture / Design

The system implements Clean Architecture, cleanly separating concerns across four main layers to ensure the business logic remains agnostic of external delivery mechanisms.

- **Core Module (`src/core`)**: Contains domain models, abstract interfaces, configuration schemas, and custom exceptions.
- **Application Module (`src/app`)**: orchestrates the `agent_loop`, `amadeus_service`, and `tool_registry`.
- **Infrastructure Module (`src/infra`)**: Houses concrete implementations for LLMs (router and adapters), caching (`cache_service`), persistence repositories, speech processing (`tts_router`), and external API tool integrations.
- **API Module (`src/api`)**: The presentation layer containing FastAPI routes, authentication middleware, rate limiting, and server bootstrapping.

```text
API Layer (FastAPI) [JWT & Rate Limits] → App Services (Agent Loop) → Core Domain (Interfaces)
                                                    ↓
                     Infrastructure Layer (Postgres, Redis, LLMs, System Tools)
```

## Setup & Installation

**Prerequisites:**
- Docker & Docker Compose
- Python 3.11+ (if running locally without Docker)
- Required API Keys (Gemini, Groq)

**Environment Variables:**
Create a `.env` file referencing `.env.example`:
- `ENV` (development/production)
- `GEMINI_API_KEY`, `GROQ_API_KEY` (Required for LLMs)
- `DATABASE_URL` (Optional override)
- `REDIS_URL` (Optional override)
- `WEATHER_API_KEY` , `NEWS_API_KEY` (Optional)

**Dependency Installation (Local Run):**
1. Ensure `uv` or `pip` is available.
2. Run `pip install -e .[all]` or `uv pip install -e .[all]`.

**Running the Project via Docker:**
```bash
# Start the development environment with PostgreSQL and Redis
docker-compose up --build
```
For production:
```bash
docker-compose --profile prod up --build -d
```

## Usage

Once running, the API server is available at `http://localhost:8000`. 
*(Note: Requires valid JWT tokens passed in Headers for protected endpoints).*

**Chat Endpoint Example:**
```bash
curl -X POST "http://localhost:8000/api/v1/chat" \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer <JWT_TOKEN>" \
     -d '{"message": "Start a 25-minute Pomodoro timer", "source": "cli"}'
```

**Conversation History:**
```bash
curl -X GET "http://localhost:8000/api/v1/chat/history?session_id=<SESSION_ID>" \
     -H "Authorization: Bearer <JWT_TOKEN>"
```

**List Available Tools:**
```bash
curl -X GET "http://localhost:8000/api/v1/chat/tools" \
     -H "Authorization: Bearer <JWT_TOKEN>"
```

## Project Structure

- `src/api/`: Presentation layer, FastAPI routes (`chat.py`, `health.py`), standard middleware, and authentication validators.
- `src/app/`: Application layer featuring `AmadeusService`, core `agent_loop.py`, and `tool_registry.py`.
- `src/core/`: Domain layer with settings (`config.py`), base interface definitions, and core domain models.
- `src/infra/`: Infrastructure implementations corresponding to database repositories, multi-LLM adapters, voice interfaces (`edge-tts`), caching services, and external APIs.
- `.github/workflows/`: CI/CD automation pipelines.
- `tests/`: End-to-end and unit testing utilities relying on pytest and testcontainers.

## Known Limitations

- **Frontend Interface Missing**: The system strictly operates as a backend daemon. Interaction currently relies on raw HTTP requests or custom shell clients.
- **Resource Intensity**: Local TTS and Whisper models (`faster-whisper`) may consume significant CPU/RAM if running without hardware acceleration.

## Future Improvements

- Add asynchronous long-running task processing via Celery or similar workers rather than generic `asyncio.sleep()`.
- Implement native WebSocket support for streaming real-time LLM responses and TTS audio data directly to clients.
- Add robust user registration and role-based access control (RBAC) to support multi-tenant usage.

## Screenshots / Demo

*(Add Demo Video / Architecture Diagrams / Output screenshots here)*
