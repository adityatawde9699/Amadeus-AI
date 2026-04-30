# Amadeus-AI Wiki

> **v3.2.1 — Security Hardening & Observability Edition**  
> A production-grade, multi-modal AI assistant backend built on Clean Architecture — text, voice, and tool execution unified under one API.

---

## What is Amadeus?

Amadeus is a **FastAPI-based AI assistant backend** that solves three concrete problems with existing open-source assistants:

| Problem | Amadeus Solution |
|---|---|
| Single LLM provider — fails when rate-limited | Multi-provider fallback router with Redis-backed daily quota tracking |
| No authentication boundary | JWT Bearer auth on all protected routes with RBAC |
| No local tool execution | 60+ tools spanning system, productivity, communication, and code sandboxing |

---

## What's New in v3.2.1

- **SEC-01 — Prompt Injection Resistance** — User input wrapped in `<user_task>` XML tags; ReAct control tokens neutralised with `[BLOCKED:TOKEN]` before LLM sees them
- **SEC-02 — WhatsApp HMAC** — Every webhook POST verified against `X-Hub-Signature-256`; forged payloads → HTTP 403
- **SEC-03 — Telegram Authorization** — `MASTER_TELEGRAM_CHAT_ID` allowlist; unknown senders receive `"Unauthorized."` and are dropped
- **SEC-06 — Secure SECRET_KEY** — Auto-generates cryptographically-secure ephemeral key if not configured; no more `"fallback"` literal
- **CQ-01/02 — Filesystem Sandboxing** — `copy_file`, `move_file`, `create_folder` all enforce `SEARCH_ALLOWED_DIRS` via `_assert_in_allowed_dirs()`
- **ARCH-04 — Qdrant Init Lock** — `asyncio.Lock()` prevents FileLock collision from concurrent `initialize()` races
- **DR-01/02/03 — Daemon Reliability** — Autonomous loop task tracked + done-callback; AgentOrchestrator.shutdown() implemented; APScheduler uses `wait=True`
- **IMessagingAdapter Protocol** — Unified `Protocol` for Telegram/WhatsApp/Slack — see `src/infra/messaging/protocols.py`
- **Health Probes** — `/api/v1/health/live` (liveness) and `/api/v1/health/ready` (readiness with per-dependency 503 map)
- **Per-Tool Prometheus Metrics** — `amadeus_tool_duration_seconds` Histogram + `amadeus_tool_executions_total` Counter + `amadeus_memory_errors_total` Counter
- **Test Suite** — 20 new unit tests in `tests/unit/test_security_hardening.py` and `tests/unit/test_agent_reliability.py`

---

## Wiki Pages

| Section | Description |
|---|---|
| [[Architecture]] | Clean Architecture layers, request lifecycle, LLM routing pipeline, voice pipeline, memory tiers |
| [[Quick-Start]] | Prerequisites, local installation, Docker development & production |
| [[Configuration-Reference]] | All `.env` variables — required, LLM providers, optional integrations |
| [[Core-Systems]] | Semantic Router, Omni-Workspace RAG, Flash Memory Cache, Agent Orchestrator, HITL |
| [[Tool-Registry]] | All 60+ tools organized by category |
| [[API-Reference]] | Authentication, chat, voice WebSocket, messaging, tasks, health endpoints |
| [[Redis-Quota-Tracking]] | Daily LLM quota counters, Redis key schema, cost alerts |
| [[Messaging-Integrations]] | Telegram, WhatsApp, Email setup guides |
| [[Security-Model]] | Auth, network isolation, secret management, tool execution safety, prompt injection defence |
| [[Deployment]] | Railway, Docker Compose, Windows Daemon |
| [[Development-Guide]] | Adding LLM providers & tools, testing, coding standards |
| [[Observability]] | Prometheus metrics, health probes, structured logging, Sentry |
| [[Known-Limitations-and-Roadmap]] | Current gaps and planned improvements |
| [[Changelog]] | Version history highlights |

---

## Quick Links

- **Repository:** [github.com/adityatawde9699/Amadeus-AI](https://github.com/adityatawde9699/Amadeus-AI)
- **API Docs (local):** `http://localhost:8000/docs` *(requires `DEBUG=true`)*
- **Liveness:** `GET /api/v1/health/live`
- **Readiness:** `GET /api/v1/health/ready`
- **Issues:** [GitHub Issues](https://github.com/adityatawde9699/Amadeus-AI/issues)
- **Security:** [SECURITY.md](https://github.com/adityatawde9699/Amadeus-AI/blob/main/SECURITY.md)
- **Contributing:** [CONTRIBUTING.md](https://github.com/adityatawde9699/Amadeus-AI/blob/main/CONTRIBUTING.md)
