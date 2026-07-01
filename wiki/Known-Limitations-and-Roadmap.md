# Known Limitations & Roadmap

---

## Current Limitations

| Limitation | Notes |
|---|---|
| No token refresh / password reset | Registration and JWT login exist (`POST /api/v1/auth/register`, `POST /api/v1/auth/jwt/login` via fastapi-users), but there is no refresh-token or password-reset flow |
| Static proactive loop session list | `session_ids` in `AutonomousObservationLoop` is hardcoded — not loaded from DB |
| Windows-only Office tools | `create_excel_spreadsheet`, `create_word_document`, `send_outlook_email` require `pywin32` and only work on Windows |
| No mobile/browser SDK | The chat, messaging, and tasks endpoints must be called with raw HTTP |
| **SEC-07 — Metrics unauthenticated** | `/api/v1/metrics` has no auth. Restrict access at the network/proxy layer in production deployments |

---

## Resolved in v6.0.0

| Fixed Issue | Resolution |
|---|---|
| Any Telegram user could control the daemon | SEC-03: `MASTER_TELEGRAM_CHAT_ID` allowlist enforced |
| No WhatsApp webhook HMAC verification | SEC-02: `X-Hub-Signature-256` HMAC enforced; forged payloads → 403 |
| Prompt injection in ReAct prompt | SEC-01: `<user_task>` boundary + `[BLOCKED:TOKEN]` neutralisation |
| Filesystem exfiltration via `copy_file`/`move_file` | CQ-01/02: `_assert_in_allowed_dirs()` enforced on all path operations |
| Per-message `AmadeusService` construction (OOM) | ARCH-01: DI singleton reused across all messages |
| AgentOrchestrator shutdown never executed (zombie tasks) | DR-02: `shutdown()` implemented with `cancel()` + `await` |
| APScheduler `wait=False` dropped in-flight jobs | DR-03: `shutdown(wait=True)` |
| Autonomous loop task untrackable | DR-01: task stored + done-callback registered |
| `SECRET_KEY` fallback literal | SEC-06: auto-generated cryptographically-secure ephemeral key |
| Memory deduplication (flooding) | P6-T7: Content-based `uuid5` point IDs — idempotent upserts |

---

## Planned Improvements

### Authentication
- Refresh-token and password-reset flows on top of the existing fastapi-users register/login endpoints
- SEC-07: `/api/v1/metrics` authentication (Bearer or network-level)

### SDK
- Mobile / browser SDK for the chat, messaging, and tasks endpoints

### Observability
- Grafana dashboard for Prometheus cost gauges and tool latency histograms

### Platform
- Dynamic skill loading — mount new tools as sandboxed Docker containers at runtime without restarting
- Proactive loop session discovery — load `session_ids` from PostgreSQL instead of a static list
- `IMessagingAdapter` Protocol adoption in the `TelegramAdapter` and email adapter concrete implementations

---

*← [[Observability]] | [[Changelog]] →*
