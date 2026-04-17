# Changelog

All notable changes to Amadeus-AI are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- `LLMAdapter` abstract base class (`src/core/interfaces/llm.py`) — all provider adapters must now conform to this interface, enabling static type-checking via mypy
- `LlamaCppAdapter` now injects conversation history from `ConversationContext` into the messages list (multi-turn memory now works with local GGUF models)
- `LlamaCppAdapter` guards `flash_attn`, `type_k`, `type_v` parameters with `inspect.signature` introspection — prevents `TypeError` on older `llama-cpp-python` builds
- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md` — community health files
- GitHub Issue templates (bug report, feature request) and Pull Request template
- `CODEOWNERS` file for automatic reviewer assignment

### Fixed
- **Critical**: `LlamaCppAdapter` was raising `LLMRateLimitError` for non-rate-limit conditions (import error, model load failure, path not found), causing silent fallback to cloud providers. Now uses `ConfigurationError`, `LLMConnectionError`, and `LLMResponseError` appropriately
- **Critical**: `LLMRateLimitError` was called with full sentences as the `service` argument throughout `ollama_adapter.py` and `router.py`. Now called with the short provider identifier as intended
- `LLMRouter` class docstring now correctly reflects the actual routing priority (`LlamaCpp → Ollama → Groq → Gemini → OpenAI`) instead of the obsolete `Groq → Gemini → OpenAI`
- `container.py` Groq, Gemini, and OpenAI adapter initialization failures are now logged via `logger.warning(...)` instead of silently swallowed with `except Exception: pass`
- CI coverage gate raised from 60% to 80% to match the `pyproject.toml` `fail_under` setting
- GitGuardian CI step now has `continue-on-error: true` so a missing `GITGUARDIAN_API_KEY` secret doesn't block the entire quality pipeline

### Security
- `.env.prod`, `.env.staging`, `.env.local`, and `.env.*.local` added to `.gitignore` to prevent accidental secret commits

---

## [2.0.0] — 2026-04-17

### Added
- Clean Architecture rewrite: `src/core/`, `src/app/`, `src/infra/`, `src/api/` layers
- **LLM Router** with priority-based fallback across LlamaCpp, Ollama, Groq, Gemini, OpenAI
- **LlamaCppAdapter** — 100% offline GGUF model inference via `llama-cpp-python`
- **OllamaAdapter** — local server inference with model management (pull, list, delete)
- **GeminiAdapter** — Google Gemini 2.5 Flash via `google-genai`
- **GroqAdapter** — Groq free-tier LLM (Llama 3.3 70B)
- **OpenAIAdapter** — OpenAI GPT-4o backup for high-complexity tasks
- FastAPI REST API with JWT authentication (`fastapi-users`)
- Telegram Bot integration with webhook + long-polling support
- WhatsApp integration via Meta Cloud API
- Vector memory with ChromaDB / Qdrant for long-term semantic recall
- APScheduler background jobs for proactive assistant checks
- Prometheus metrics via `prometheus-fastapi-instrumentator`
- Sentry error tracking integration
- Redis-backed quota tracking for multi-worker LLM usage
- Docker + docker-compose for containerized deployment
- Railway deployment configuration
- GitHub Actions CI/CD pipeline (lint, type-check, test, Docker build, auto-release)
- Windows service installer (`scripts/install_windows_service.ps1`)
- Voice pipeline: Whisper STT + Edge-TTS + ElevenLabs TTS
- Tool system: filesystem, system monitoring, productivity (tasks, pomodoro, calendar)
- HITL (Human-in-the-Loop) confirmation gate for destructive tool operations
- Alembic database migrations

---

## [1.0.0] — Legacy (Amadeus/)

Initial prototype — single-file assistant with basic GPT-2/Gemini integration.

[Unreleased]: https://github.com/adityatawde9699/Amadeus-AI/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/adityatawde9699/Amadeus-AI/releases/tag/v2.0.0
