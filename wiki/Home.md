# Amadeus-AI Wiki

> **v5.0.0-beta — MCP & Daemon Hardening**
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

## What's New in v5.0.0

- **Cognitive Core (Phase 1)** — Fully migrated to a deterministic `LangGraph` async state machine, resolving brittle ReAct loop parsing errors.
- **Deep RAG Memory (Phase 2)** — Replaced Qdrant with `Turbovec` + `aiosqlite`. Achieved massive 4-bit quantization compression (up to 16x scale reduction) with zero penalties, while running entirely in-process.
- **MCP Tool Integration (Phase 3)** — Amadeus now dynamically discovers and consumes external tool capabilities via the Model Context Protocol.
- **24/7 Daemon Hardening (Phase 6)** — Systemd daemon fully fortified with memory/CPU quotas, burst restarts, and proper ASGI SIGTERM signal handling.
- **Proactive Garbage Collection** — Background autonomous loops now correctly invoke `prune_stale_memories` to prevent Turbovec index bloating.

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
