<div align="center">

# Amadeus AI

**Local-first autonomous AI runtime — persistent memory, a tool-permission engine, and LangGraph orchestration, running headless on your own machine.**

[![CI Pipeline](https://github.com/adityatawde9699/Amadeus-AI/actions/workflows/main.yml/badge.svg)](https://github.com/adityatawde9699/Amadeus-AI/actions)
[![Release](https://img.shields.io/badge/release-v6.0.0-blue.svg)](https://github.com/adityatawde9699/Amadeus-AI/releases)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE.txt)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

[Quick Start](#quick-start) · [Features](#features) · [Architecture](#architecture) · [Documentation](#documentation) · [Security](#security)

</div>

<!-- Add a terminal GIF or dashboard screenshot here — a 30s demo converts far better than text.
     e.g. ![Amadeus demo](docs/assets/demo.gif) -->

---

Amadeus is a **secure autonomous AI operating layer** — a persistent cognitive runtime, not just a chatbot. It runs as a **headless daemon** that plans, acts, verifies, and remembers, built on Clean Architecture with an explicit LangGraph execution graph you can pause, audit, and resume.

It's designed to be **local-first**: inference can run entirely on your own hardware (local GGUF models), and `LOCAL_ONLY_MODE=true` disables every cloud provider so nothing leaves the machine.

## Why Amadeus?

| Most agent stacks | Amadeus |
|---|---|
| Brittle ReAct loops that lose state | **Deterministic LangGraph state machine** — every task is an auditable, resumable execution graph |
| Tools bolted into core code | **Hot-pluggable tools** — drop a `.py` file into `plugins/`, loaded on next restart |
| No security layer on tool calls | **Tool Policy Engine** — risk levels + graduated permission profiles that **fail closed** |
| "Local" sandboxes that are trivially escapable | **Hardened Docker sandbox**, disabled by default, refuses to run untrusted code when unavailable |
| Cloud-only inference | **Local-first fallback chain**: local GGUF → Groq → Gemini |
| Amnesia between sessions | **Persistent episodic + semantic memory** in PostgreSQL + a local vector store |

## Quick Start

**Requirements:** Python 3.11+, [`uv`](https://docs.astral.sh/uv/), and at least one LLM API key ([Groq is free](https://console.groq.com)).

```bash
git clone https://github.com/adityatawde9699/Amadeus-AI.git
cd Amadeus-AI
uv sync --all-extras --dev

cp .env.example .env          # set SECRET_KEY and GROQ_API_KEY (minimum)
uv run alembic upgrade head   # initialise the database
```

Then start whichever interface fits your use case:

```bash
# API host — REST + admin surface, interactive docs at http://localhost:8000/docs
uv run python -m src.transports.fastapi_transport

# Telegram-first local daemon (needs TELEGRAM_BOT_TOKEN + MASTER_TELEGRAM_CHAT_ID)
uv run amadeus-daemon
```

Prefer containers? `docker-compose up --build -d` brings up the API, worker, Postgres, Redis, and Qdrant.
Full walkthrough → [Quick Start wiki](https://github.com/adityatawde9699/Amadeus-AI/wiki/Quick-Start).

> **Minimum viable setup:** Python 3.11 + ~1 GB RAM + a free `GROQ_API_KEY`. Redis and the vector store are optional — the daemon degrades gracefully without them.

## Features

- **Autonomous agent lifecycle** — plan-driven reasoning, self-reflection on tool failures, and durable state that survives restarts.
- **70+ sandboxed tools** — system control, networking, filesystem, productivity, and research, each mapped to a risk level.
- **Fail-closed security** — graduated permission profiles, prompt-injection resistance, SSRF egress protection, and pre-auth rate limiting.
- **Local-first inference** — priority-ordered LLM routing with Redis-backed daily quota tracking; `LOCAL_ONLY_MODE` for 100% privacy.
- **Persistent memory** — every plan, step, and reflection is stored in PostgreSQL for a full behavioral audit; semantic recall via a local vector store.
- **Omni-Workspace RAG** — hybrid BM25 + dense retrieval so the agent can search your codebase and local files.
- **Multi-transport** — one `AmadeusService` behind FastAPI (REST + voice WebSocket), Telegram, and a CLI.

```text
LLM routing:  LlamaCpp (local GGUF)  →  Groq (Llama 3.3 70B)  →  Gemini 2.5 Flash
```

## Architecture

Amadeus follows Clean Architecture — dependencies point inward, and the core layer has zero external dependencies.

```text
Clients — HTTP · Telegram · CLI
    ↓
Transport — src/transports/
    ↓
Application — AmadeusService · LangGraph · ToolDispatcher
   ↙            ↓
Core — domain models · interfaces · settings
   ↘
Infrastructure — LLM adapters · DB · cache · memory · tools
    ↓
Data — PostgreSQL · Redis · Vector store
```

Deep dives — [Architecture](https://github.com/adityatawde9699/Amadeus-AI/wiki/Architecture) · [Core Systems](https://github.com/adityatawde9699/Amadeus-AI/wiki/Core-Systems) · [LLM Routing & Quota](https://github.com/adityatawde9699/Amadeus-AI/wiki/Redis-Quota-Tracking).

## Documentation

The full documentation lives in the **[project wiki](https://github.com/adityatawde9699/Amadeus-AI/wiki)**:

| Page | What's inside |
|---|---|
| [Quick Start](https://github.com/adityatawde9699/Amadeus-AI/wiki/Quick-Start) | Prerequisites, local install, Docker, offline mode |
| [Configuration Reference](https://github.com/adityatawde9699/Amadeus-AI/wiki/Configuration-Reference) | Every `.env` variable explained |
| [Architecture](https://github.com/adityatawde9699/Amadeus-AI/wiki/Architecture) | Layer diagram, request lifecycle, memory tiers |
| [Tool Registry](https://github.com/adityatawde9699/Amadeus-AI/wiki/Tool-Registry) | All 70+ tools by category |
| [API Reference](https://github.com/adityatawde9699/Amadeus-AI/wiki/API-Reference) | Chat, messaging, voice, tasks, health endpoints |
| [Security Model](https://github.com/adityatawde9699/Amadeus-AI/wiki/Security-Model) | Auth, sandboxing, tool execution safety |
| [Deployment](https://github.com/adityatawde9699/Amadeus-AI/wiki/Deployment) | Docker Compose, systemd, Railway, Windows service |
| [Development Guide](https://github.com/adityatawde9699/Amadeus-AI/wiki/Development-Guide) | Adding tools & LLM providers, testing, coding standards |
| [Known Limitations & Roadmap](https://github.com/adityatawde9699/Amadeus-AI/wiki/Known-Limitations-and-Roadmap) | Current gaps and what's next |

## Tech Stack

`Python 3.11+` · `FastAPI` · `SQLAlchemy 2.0` · `PostgreSQL` · `Redis` · `LangGraph` · `Groq (Llama 3.3)` · `Gemini` · `llama-cpp-python` · `ONNX Runtime` · `Turbovec` · `Docker`

## Security

Amadeus is built to **fail closed** — when a security-relevant precondition is missing, it denies rather than allows. Highlights: graduated tool permissions, a Docker-only code sandbox (disabled by default), SSRF egress protection, a Telegram allowlist that rejects all senders when unset, and pre-auth rate limiting.

Found a vulnerability? Please follow the [Security Policy](SECURITY.md) — do **not** open a public issue.

## Contributing

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md) and the [Development Guide](https://github.com/adityatawde9699/Amadeus-AI/wiki/Development-Guide), and please observe the [Code of Conduct](CODE_OF_CONDUCT.md). Good first issues are labelled in the [issue tracker](https://github.com/adityatawde9699/Amadeus-AI/issues).

## License

Apache License 2.0 — see [LICENSE.txt](LICENSE.txt). Copyright © 2024 Aditya Tawde.

<div align="center">

**[Aditya Tawde](https://github.com/adityatawde9699)** · [Report a bug](https://github.com/adityatawde9699/Amadeus-AI/issues/new) · [Changelog](CHANGELOG.md)

</div>
