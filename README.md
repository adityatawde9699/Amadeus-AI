# Project Overview

Amadeus-AI is a backend service for an AI-powered voice and text assistant built using Clean Architecture principles in Python. It provides an extensible agent loop that processes user commands, manages conversation history, and invokes various system and productivity tools. The architecture strictly separates core domain models from application logic, infrastructure integrations, and API presentation, ensuring maintainability and robust dependency management.

## Features

- **Conversational AI Core**: Orchestrates input processing using Google's Gemini models.
- **Voice Interface**: Supports speech recognition and text-to-speech workflows (via `faster-whisper` and `pyttsx3`).
- **Tool Execution Engine**: Dynamically executes tools across categories including system operations, productivity (Pomodoro, calendar), and monitoring.
- **Conversation Persistence**: Async SQLite and PostgreSQL support for persistent chat history.
- **RESTful API**: Exposes endpoints for chat, tool listing, and history retrieval.
- **Observability Hooks**: Integrates Structlog, Sentry, and Prometheus.

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
- Redis

**APIs & Services:**
- Google Generative AI (Gemini)
- OpenWeatherMap API & News API integrations
- Sentry (Error tracking)

**Development:**
- Testing: Pytest, pytest-asyncio, Testcontainers
- Code Quality: Ruff, Black, Mypy

## Architecture / Design

The system implements Clean Architecture, cleanly separating concerns across four main layers to ensure the business logic remains agnostic of external delivery mechanisms.

- **Core Module (`src/core`)**: Contains domain models, abstract interfaces, configuration schemas, and custom exceptions.
- **Application Module (`src/app`)**: orchestrates the `agent_loop`, `amadeus_service`, and `tool_registry`.
- **Infrastructure Module (`src/infra`)**: Houses concrete implementations for LLMs (`gemini_adapter`), persistence repositories, speech processing, and external API tool integrations.
- **API Module (`src/api`)**: The presentation layer containing FastAPI routes, middleware, and server bootstrapping.

```text
API Layer (FastAPI) → App Services (Agent Loop) → Core Domain (Interfaces)
                             ↓
Infrastructure Layer (Postgres, Gemini API, System Tools)
```

## Setup & Installation

**Prerequisites:**
- Docker & Docker Compose
- Python 3.11+ (if running locally without Docker)
- Required API Keys (Gemini)

**Environment Variables:**
Create a `.env` file referencing `.env.example`:
- `ENV` (development/production)
- `GEMINI_API_KEY` (Required)
- `DATABASE_URL` (Optional override)
- `WEATHER_API_KEY` , `NEWS_API_KEY` (Optional)

**Dependency Installation (Local Run):**
1. Ensure `uv` or `pip` is available.
2. Run `pip install -e .[all]` or `uv pip install -e .[all]`.

**Running the Project via Docker:**
```bash
# Start the development environment with PostgreSQL
docker-compose up --build
```
For production:
```bash
docker-compose --profile prod up --build -d
```

## Usage

Once running, the API server is available at `http://localhost:8000`.

**Chat Endpoint Example:**
```bash
curl -X POST "http://localhost:8000/chat" \
     -H "Content-Type: application/json" \
     -d '{"message": "Start a 25-minute Pomodoro timer", "source": "cli"}'
```

**Conversation History:**
```bash
curl -X GET "http://localhost:8000/chat/history?session_id=<SESSION_ID>"
```

**List Available Tools:**
```bash
curl -X GET "http://localhost:8000/chat/tools"
```

## Project Structure

- `src/api/`: Presentation layer, FastAPI routes (`chat.py`, `health.py`), and middleware.
- `src/app/`: Application layer featuring the primary `AmadeusService`, `agent_loop.py`, and `tool_registry.py`.
- `src/core/`: Domain layer with settings (`config.py`), base interfaces, and core domain models.
- `src/infra/`: Infrastructure implementations corresponding to database repositories, `gemini_adapter.py`, and local system tools.
- `tests/`: End-to-end and unit testing utilities relying on pytest and testcontainers.

## Known Limitations

- **Single LLM Provider**: Currently hard-coupled to `gemini_adapter.py` (Google Generative AI); lacking Anthropic/OpenAI fallback implementations despite internal architecture allowances.
- **Authentication**: No explicit OAuth or structural user authentication middleware exposed on internal `/chat` routes (assumes private or internal-only API access).

## Future Improvements

- Provide provider-agnostic adapter subclasses to cleanly support OpenAI or local models.
- Implement explicit API rate limiting or scoped API-key authorization middleware.
- Extend CI/CD pipeline automation setup (e.g., GitHub Actions).

## Screenshots / Demo

*(Add Demo Video / Architecture Diagrams / Output screenshots here)*
