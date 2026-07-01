# Security Model

Amadeus is designed with defence-in-depth across authentication, network isolation, secret management, prompt injection resistance, and tool execution safety.

> **v4.0.0** introduced the centralized **Tool Policy Engine** for deterministic safety gates.

---

## Authentication

| Aspect | Implementation |
|---|---|
| Algorithm | JWT HS256 via `python-jose` |
| `exp` claim | Required in production; accepted without `exp` in development |
| Rate limiting | Keyed by `sub` (user ID); falls back to IP for unauthenticated requests (SlowAPI) |
| Redis fallback | If Redis is unreachable at startup, rate limiter falls back to in-memory storage (v6.0.0+) |
| RBAC | `admin` / `user` / `guest` roles enforced per route |

---

## Tool Policy Engine (v4.0.0+)

**File:** `src/infra/tools/policy.py`

The `ToolExecutor` now passes every request through a deterministic policy layer before execution. This engine evaluates the tool's `RiskLevel` against the active `PermissionProfile`.

### Risk Levels

| Level | Description | Example Tools |
|---|---|---|
| `LOW` | Read-only, safe local operations | `get_time`, `list_tasks`, `get_cpu_usage` |
| `MEDIUM` | Modifies local non-system state | `add_task`, `set_volume`, `create_note` |
| `HIGH` | Network external or sensitive local | `send_email`, `web_search`, `delete_file` |
| `CRITICAL` | System destructive or code execution | `terminate_process`, `execute_python_script` |

### Graduated Permission Profiles (v6.0.0)

Three strictly rank-ordered profiles, mapped from the caller's role:

| Profile | Role mapping | Grants |
|---|---|---|
| `READ_ONLY` | `guest` / anonymous | `LOW` tools only; blocks anything with `modifies_filesystem=True` or `modifies_system_state=True` |
| `STANDARD` | `user` / Telegram allowlisted | Adds `MEDIUM` (and vetted `HIGH`) tools |
| `SYSTEM_FULL` | `admin` / `TELEGRAM_ELEVATED_CHAT_IDS` | Full access, including `CRITICAL` tools |

### Policy Enforcement

- **`min_permission` boundary**: `ToolCapability` carries a `min_permission`; the engine **denies any tool whose required profile outranks the caller**. `ToolExecutor.execute()` defaults to `READ_ONLY` and requires an explicit `RequestContext`.
- **Denylist removed**: the previous bypassable command-substring denylist (`rm -rf /`, `mkfs`, …) was **removed as an authorization mechanism** in v6.0.0 — authorization is now profile-based, not string-matched.
- **Destructive Guard**: tools tagged `CRITICAL` always require the `requires_confirmation` flag (human-in-the-loop).
- **Process Protection**: explicitly blocks attempts to terminate protected system processes (e.g., `explorer.exe`, `kernel`).

---

## Messaging Channel Authorization

### SEC-03 — Telegram (v6.0.0+)

`TelegramAdapter._handle_message()` enforces a `MASTER_TELEGRAM_CHAT_ID` allowlist. Set comma-separated chat IDs in `.env`:

```env
MASTER_TELEGRAM_CHAT_ID=123456789,987654321
```

Messages from any other `chat_id` receive `"Unauthorized."` and are dropped before processing.

---

## Prompt Injection Defence

### SEC-01 (v6.0.0+)

All user task text is sanitised before entering the LangGraph prompt:

1. Wrapped in `<user_task>...</user_task>` XML boundary tags
2. LangGraph control tokens found in the user input (`Action:`, `Thought:`, `Action Input:`, `Observation:`, `FINISH`) are replaced with `[BLOCKED:TOKEN]` markers

This prevents users from injecting LLM directives via Telegram or the HTTP API to make the agent execute arbitrary tools.

---

## Secret Management

- All API keys loaded from environment variables — **never hardcoded**.
- `.env.prod`, `.env.staging`, `.env.local` are in `.gitignore`.
- **GitGuardian pre-commit hook** scans for leaked secrets before every commit.
- **SEC-06 (v6.0.0+)**: `SECRET_KEY` auto-generates a cryptographically-secure 32-byte ephemeral key at startup if not set. A `WARNING` is logged urging operators to set a persistent key.
- **IPC Token (v6.0.0+)**: `data/ipc_secret.token` (`chmod 600`). Corruption (non-UTF-8, empty, OS error) is caught specifically; a `CRITICAL` log entry names the file path and warns that connected IPC clients will need to re-authenticate before regenerating.

---

## Tool Execution Safety

### HITL Confirmation

Destructive tools require explicit approval with a **60-second timeout** (auto-deny on timeout):

```
terminate_process · terminate_program · delete_file · execute_python_script
fs_write_file · send_outlook_email · send_email · send_slack_message
```

### Filesystem Sandboxing (v6.0.0+)

`copy_file`, `move_file`, and `create_folder` all call `_assert_in_allowed_dirs()` which resolves the full canonical path and validates it against `SEARCH_ALLOWED_DIRS`:

```python
# .env
SEARCH_ALLOWED_DIRS=/home/user/Documents,/home/user/Downloads
```

Path traversal attempts (e.g. `../../etc/passwd`) return `"Access denied: path …"` without touching the filesystem.

### Code Execution Sandbox

> **Changed in v6.0.0 — fails closed.** The escapable in-process
> (`LocalSandboxExecutor`) mode was **removed entirely** — it was trivially
> escapable while advertised as isolated. There is no local execution fallback.

Code execution is **disabled by default**. `SANDBOX_MODE` is a
`Literal["disabled", "docker"]`:

| Mode | Technology | Behavior |
|---|---|---|
| `disabled` | — | **Default.** `execute_python_script` returns "unavailable". |
| `docker` | Ephemeral container | Runs untrusted code in a hardened, locked-down container. |

When `docker` is selected but Docker is unavailable, execution is **refused**
(fail closed) rather than silently downgraded. The container is hardened with a
read-only root filesystem, all Linux capabilities dropped, `no-new-privileges`,
networking disabled, a non-root user, PID/memory/swap/CPU caps, a small writable
`tmpfs`, a pinned image, and an enforced kill timeout.

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
| Metrics | `/api/v1/metrics` includes `amadeus_tool_executions_total` for per-tool result breakdown |
| Episodic Memory | Every plan step and reflection is stored in the database for post-hoc behavioral audit. |

---

## Reporting Vulnerabilities

See [SECURITY.md](https://github.com/adityatawde9699/Amadeus-AI/blob/main/SECURITY.md) for the responsible disclosure process.

---

*← [[Messaging-Integrations]] | [[Deployment]] →*
