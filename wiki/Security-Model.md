# Security Model

Amadeus is designed with defence-in-depth across authentication, network isolation, secret management, prompt injection resistance, and tool execution safety.

> **v3.2.1** hardened all six critical audit findings. See [CHANGELOG.md](https://github.com/adityatawde9699/Amadeus-AI/blob/main/CHANGELOG.md) for details.

---

## Authentication

| Aspect | Implementation |
|---|---|
| Algorithm | JWT HS256 via `python-jose` |
| `exp` claim | Required in production; accepted without `exp` in development |
| Rate limiting | Keyed by `sub` (user ID); falls back to IP for unauthenticated requests (SlowAPI) |
| Redis fallback | If Redis is unreachable at startup, rate limiter falls back to in-memory storage (v3.2.1+) |
| RBAC | `admin` / `user` / `guest` roles enforced per route |

**Guest-tier users** are placed in `READ_ONLY` profile — all `requires_confirmation=True` tools are hard-blocked regardless of any callback override.

---

## Messaging Channel Authorization

### SEC-03 — Telegram (v3.2.1+)

`TelegramAdapter._handle_message()` enforces a `MASTER_TELEGRAM_CHAT_ID` allowlist. Set comma-separated chat IDs in `.env`:

```env
MASTER_TELEGRAM_CHAT_ID=123456789,987654321
```

Messages from any other `chat_id` receive `"Unauthorized."` and are dropped before processing.

### SEC-02 — WhatsApp HMAC Verification (v3.2.1+)

Every `POST /api/v1/webhooks/whatsapp` verifies the `X-Hub-Signature-256` header:

```python
expected = "sha256=" + hmac.new(WHATSAPP_APP_SECRET, body, sha256).hexdigest()
# Forged payloads → HTTP 403
```

Set `WHATSAPP_APP_SECRET=<your Meta App Secret>` in `.env`.

---

## Prompt Injection Defence

### SEC-01 (v3.2.1+)

All user task text is sanitised before entering the ReAct prompt:

1. Wrapped in `<user_task>...</user_task>` XML boundary tags
2. ReAct control tokens found in the user input (`Action:`, `Thought:`, `Action Input:`, `Observation:`, `FINISH`) are replaced with `[BLOCKED:TOKEN]` markers

This prevents users from injecting LLM directives via Telegram, WhatsApp, or the HTTP API to make the agent execute arbitrary tools.

---

## Secret Management

- All API keys loaded from environment variables — **never hardcoded**.
- `.env.prod`, `.env.staging`, `.env.local` are in `.gitignore`.
- **GitGuardian pre-commit hook** scans for leaked secrets before every commit.
- **SEC-06 (v3.2.1+)**: `SECRET_KEY` auto-generates a cryptographically-secure 32-byte ephemeral key at startup if not set. A `WARNING` is logged urging operators to set a persistent key.
- **IPC Token (v3.2.1+)**: `data/ipc_secret.token` (`chmod 600`). Corruption (non-UTF-8, empty, OS error) is caught specifically; a `CRITICAL` log entry names the file path and warns that connected IPC clients will need to re-authenticate before regenerating.
- `WHATSAPP_APP_SECRET`: Required for SEC-02 HMAC verification. Set in `.env`.

---

## Tool Execution Safety

### HITL Confirmation

Destructive tools require explicit approval with a **60-second timeout** (auto-deny on timeout):

```
terminate_program · delete_file · execute_python_script
fs_write_file · send_outlook_email · send_email · send_slack_message
```

### Filesystem Sandboxing (v3.2.1+)

`copy_file`, `move_file`, and `create_folder` all call `_assert_in_allowed_dirs()` which resolves the full canonical path and validates it against `SEARCH_ALLOWED_DIRS`:

```python
# .env
SEARCH_ALLOWED_DIRS=/home/user/Documents,/home/user/Downloads
```

Path traversal attempts (e.g. `../../etc/passwd`) return `"Access denied: path …"` without touching the filesystem.

### Code Execution Sandbox

`execute_python_script` runs in a Docker container with:

| Constraint | Value |
|---|---|
| Network | `--network=none` (fully isolated) |
| Memory | `--memory=128m` |
| CPU | `--cpus=0.5` |
| User | Non-root |
| Lifecycle | Auto-removed on completion |
| Timeout | 15 seconds |
| Image | `python:3.10-slim` |

---

## Network Isolation (Docker)

| Port | Exposed to Host? |
|---|---|
| `6379` (Redis) | ❌ Internal only |
| `5432` (PostgreSQL) | ❌ Internal only |
| `8000` (API) | ✅ Exposed |

Both data services are internal to the `amadeus-network` Docker bridge. There is no route from the internet to Redis or PostgreSQL without going through the application layer.

---

## Observability & Audit

| Aspect | Detail |
|---|---|
| Log format | JSON via `structlog` |
| Request tracing | `request_id` UUID attached to every request; returned as `X-Request-ID` header |
| Sensitive data | API keys, raw prompts, auth tokens are **never logged** (OWASP-hardened) |
| Log files | `data/logs/amadeus.log` (rotating, 10 MB, 5 backups) |
| Security scan | `bandit -r src/ -ll` — **0 HIGH findings** enforced in CI |
| CVE audit | `pip-audit` — **0 actionable HIGH CVEs** |
| Metrics | `/api/v1/metrics` includes `amadeus_memory_errors_total{operation}` for Qdrant failure visibility |
| Known limitation | `/api/v1/metrics` is unauthenticated (SEC-07) — restrict at network/proxy layer in production |

---

## Reporting Vulnerabilities

See [SECURITY.md](https://github.com/adityatawde9699/Amadeus-AI/blob/main/SECURITY.md) for the responsible disclosure process.

---

*← [[Messaging-Integrations]] | [[Deployment]] →*
