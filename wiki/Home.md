# Amadeus-AI Wiki

> **v3.1.0 — Semantic Router Edition**  
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

## What's New in v3.1.0

- **Zero-Training Semantic Tool Router** — replaces sklearn SVM, hot-pluggable, cosine similarity threshold 0.50
- **Hybrid Workspace Indexer** — BM25 + dense vectors + RRF fusion, incremental builds, context-augmented chunking
- **Flash Memory Cache** — Tier-1 NumPy ring buffer (100 entries, 307 KB, threshold 0.85)
- **Security hardening** — Docker network isolation, Postgres/Redis ports no longer host-exposed, `SECRET_KEY` auto-generation, `.dockerignore` tightened

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
| [[Security-Model]] | Auth, network isolation, secret management, tool execution safety |
| [[Deployment]] | Railway, Docker Compose, Windows Daemon |
| [[Development-Guide]] | Adding LLM providers & tools, testing, coding standards |
| [[Observability]] | Prometheus metrics, structured logging, Sentry |
| [[Known-Limitations-and-Roadmap]] | Current gaps and planned improvements |
| [[Changelog]] | Version history highlights |

---

## Quick Links

- **Repository:** [github.com/adityatawde9699/Amadeus-AI](https://github.com/adityatawde9699/Amadeus-AI)
- **API Docs (local):** `http://localhost:8000/docs` *(requires `DEBUG=true`)*
- **Health Check:** `GET /api/v1/health/detailed`
- **Issues:** [GitHub Issues](https://github.com/adityatawde9699/Amadeus-AI/issues)
- **Security:** [SECURITY.md](https://github.com/adityatawde9699/Amadeus-AI/blob/main/SECURITY.md)
- **Contributing:** [CONTRIBUTING.md](https://github.com/adityatawde9699/Amadeus-AI/blob/main/CONTRIBUTING.md)
