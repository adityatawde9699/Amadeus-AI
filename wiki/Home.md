# Amadeus-AI Wiki

> **v3.2.2 — Model Manager, Goal Tracking & Transport Refactor**
> A secure autonomous AI operating layer built on Clean Architecture — autonomous tool execution, long-horizon planning, and multi-transport messaging unified under a single service layer.

---

## What is Amadeus?

Amadeus is a **FastAPI-based autonomous AI backend** that provides:

| Capability | Implementation |
|---|---|
| Multi-provider LLM routing | LlamaCpp (local GGUF) → Groq → Gemini with Redis-backed daily quota tracking |
| 53 sandboxed tools | System · filesystem · productivity · information · communication |
| Long-term semantic memory | Turbovec vector store with massive 4-bit compression |
| Goal management | `GoalRepository` tracks multi-session objectives |
| Multi-transport messaging | FastAPI · Telegram · CLI all share a single `AmadeusService` |
| Local model auto-download | `ModelManager` resolves and fetches models into `Model/` on first run |

---

## What's New in v3.2.2

- **Transport Layer** — `src/api/server.py` replaced by discrete transport modules: `fastapi_transport.py`, `telegram_transport.py`, `cli_transport.py`
- **Voice Service Removed** — STT/TTS pipeline and all speech dependencies purged from the DI container
- **ModelManager** — `src/infra/model_manager.py` auto-downloads embed models and GGUF files into `Model/` on first run
- **Goal Management** — `create_goal`, `update_goal`, `list_active_goals` tools; `GoalORM` backed by PostgreSQL
- **Proactive Loop Governance** — Per-session rate limiting (`PROACTIVE_MESSAGE_LIMIT_PER_HOUR`) and dry-run mode (`PROACTIVE_DRY_RUN`)
- **Deployment** — `docker-compose.yml` and `deploy/amadeus.service` systemd unit added
- **Repository cleanup** — Removed `scratch/`, `wiki-publish/`, stale dev scripts, and empty files

---

## Wiki Pages

| Section | Description |
|---|---|
| [[Architecture]] | Layer diagram, request lifecycle, LLM routing, model resolution, memory tiers, goal management |
| [[Quick-Start]] | Prerequisites, local installation, Docker |
| [[Configuration-Reference]] | All `.env` variables — LLM providers, model directory, proactive loop |
| [[Core-Systems]] | Semantic Router, Agent Orchestrator, HITL, Flash Memory Cache |
| [[Tool-Registry]] | All 53 tools organized by category |
| [[API-Reference]] | Chat, messaging, tasks, health endpoints |
| [[Redis-Quota-Tracking]] | Daily LLM quota counters and Redis key schema |
| [[Messaging-Integrations]] | Telegram and Email setup |
| [[Security-Model]] | Auth, prompt injection defence, filesystem sandboxing, tool execution safety |
| [[Deployment]] | Docker Compose, systemd service, environment setup |
| [[Development-Guide]] | Adding LLM providers and tools, testing, coding standards |
| [[Observability]] | Prometheus metrics, health probes, structured logging |
| [[Known-Limitations-and-Roadmap]] | Current gaps and planned improvements |
| [[Changelog]] | Version history |

---

## Quick Links

- **Repository:** [github.com/adityatawde9699/Amadeus-AI](https://github.com/adityatawde9699/Amadeus-AI)
- **API Docs (local):** `http://localhost:8000/docs` *(requires `DEBUG=true`)*
- **Liveness:** `GET /api/v1/health/live`
- **Readiness:** `GET /api/v1/health/ready`
- **Issues:** [GitHub Issues](https://github.com/adityatawde9699/Amadeus-AI/issues)
- **Security:** [SECURITY.md](https://github.com/adityatawde9699/Amadeus-AI/blob/main/SECURITY.md)
- **Contributing:** [CONTRIBUTING.md](https://github.com/adityatawde9699/Amadeus-AI/blob/main/CONTRIBUTING.md)
