# Amadeus-AI Wiki

> **v6.0.0 — Security & Build Hardening**
> A secure autonomous AI operating layer built on Clean Architecture — autonomous tool execution, long-horizon planning, and multi-transport messaging unified under a single service layer.

---

## What is Amadeus?

Amadeus is a **FastAPI-based autonomous AI backend** that provides:

| Capability | Implementation |
|---|---|
| Multi-provider LLM routing | LlamaCpp (local GGUF) → Groq → Gemini with Redis-backed daily quota tracking |
| 70+ sandboxed tools | System · filesystem · productivity · information · communication |
| Long-term semantic memory | Turbovec vector store with massive 4-bit compression |
| Goal management | `GoalRepository` tracks multi-session objectives |
| Multi-transport messaging | FastAPI · Telegram · CLI all share a single `AmadeusService` |
| Local model auto-download | `ModelManager` resolves and fetches models into `Model/` on first run |

---

## What's New in v6.0.0

A **security & build hardening** release. The guiding principle is **fail closed**:
when a security-relevant precondition is missing or ambiguous, deny rather than allow.
Several previously fail-*open* behaviors now fail *closed* — see the [Changelog](https://github.com/adityatawde9699/Amadeus-AI/blob/master/CHANGELOG.md) for breaking changes.

- **Graduated permission profiles** — added `STANDARD` between `READ_ONLY` and `SYSTEM_FULL`, with a role→profile mapping. `ToolExecutor.execute()` now defaults to `READ_ONLY` and requires an explicit `RequestContext`.
- **`min_permission` authorization boundary** — the policy engine denies any tool whose required profile outranks the caller; the bypassable command-substring denylist was removed.
- **Telegram fails closed** — a bot with no valid `MASTER_TELEGRAM_CHAT_ID` allowlist rejects *every* sender; `SYSTEM_FULL` requires the new `TELEGRAM_ELEVATED_CHAT_IDS` allowlist.
- **Code execution disabled by default** — `SANDBOX_MODE` defaults to `disabled`; the escapable in-process executor was removed. The Docker sandbox is read-only, network-disabled, drops all capabilities, and enforces resource + kill-timeout caps.
- **SSRF egress guard** — `fetch_webpage_content` rejects non-public addresses (loopback, RFC1918, cloud metadata), validates every redirect hop, and caps the body size.
- **Leaner runtime** — `sentence-transformers` / `scikit-learn` moved to the `[ml-fallback]` extra; the daemon embeds via `onnxruntime` and routes via a pre-trained numpy SVM to stay within the memory budget.

---

## Wiki Pages

| Section | Description |
|---|---|
| [[Architecture]] | Layer diagram, request lifecycle, LLM routing, model resolution, memory tiers, goal management |
| [[Quick-Start]] | Prerequisites, local installation, Docker |
| [[Configuration-Reference]] | All `.env` variables — LLM providers, model directory, proactive loop |
| [[Core-Systems]] | Semantic Router, Agent Orchestrator, HITL, Flash Memory Cache |
| [[Tool-Registry]] | All 70+ tools organized by category |
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
