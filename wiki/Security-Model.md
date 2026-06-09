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
| Redis fallback | If Redis is unreachable at startup, rate limiter falls back to in-memory storage (v3.2.1+) |
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

### Policy Enforcement

- **READ_ONLY Profile**: Automatically blocks all `HIGH` and `CRITICAL` tools. Blocks any tool with `modifies_filesystem=True` or `modifies_system_state=True`.
- **Destructive Guard**: Ensures tools tagged as `CRITICAL` always have the `requires_confirmation` flag set.
- **Process Protection**: Explicitly blocks attempts to terminate protected system processes (e.g., `explorer.exe`, `kernel`).
- **Argument Tokenization**: Inspects shell commands for forbidden tokens like `rm -rf /` or `mkfs`.

---

## Messaging Channel Authorization

### SEC-03 — Telegram (v3.2.1+)

`TelegramAdapter._handle_message()` enforces a `MASTER_TELEGRAM_CHAT_ID` allowlist. Set comma-separated chat IDs in `.env`:

```env
MASTER_TELEGRAM_CHAT_ID=123456789,987654321
```

Messages from any other `chat_id` receive `"Unauthorized."` and are dropped before processing.

---

## Prompt Injection Defence

### SEC-01 (v3.2.1+)

All user task text is sanitised before entering the LangGraph prompt:

1. Wrapped in `<user_task>...</user_task>` XML boundary tags
2. LangGraph control tokens found in the user input (`Action:`, `Thought:`, `Action Input:`, `Observation:`, `FINISH`) are replaced with `[BLOCKED:TOKEN]` markers

This prevents users from injecting LLM directives via Telegram, WhatsApp, or the HTTP API to make the agent execute arbitrary tools.

---

## Secret Management

- All API keys loaded from environment variables — **never hardcoded**.
- `.env.prod`, `.env.staging`, `.env.local` are in `.gitignore`.
- **GitGuardian pre-commit hook** scans for leaked secrets before every commit.
- **SEC-06 (v3.2.1+)**: `SECRET_KEY` auto-generates a cryptographically-secure 32-byte ephemeral key at startup if not set. A `WARNING` is logged urging operators to set a persistent key.
- **IPC Token (v3.2.1+)**: `data/ipc_secret.token` (`chmod 600`). Corruption (non-UTF-8, empty, OS error) is caught specifically; a `CRITICAL` log entry names the file path and warns that connected IPC clients will need to re-authenticate before regenerating.

---

## Tool Execution Safety

### HITL Confirmation

Destructive tools require explicit approval with a **60-second timeout** (auto-deny on timeout):

```
terminate_process · terminate_program · delete_file · execute_python_script
fs_write_file · send_outlook_email · send_email · send_slack_message
```

### Filesystem Sandboxing (v3.2.1+)

`copy_file`, `move_file`, and `create_folder` all call `_assert_in_allowed_dirs()` which resolves the full canonical path and validates it against `SEARCH_ALLOWED_DIRS`:

```python
# .env
SEARCH_ALLOWED_DIRS=/home/user/Documents,/home/user/Downloads
```

Path traversal attempts (e.g. `../../etc/passwd`) return `"Access denied: path …"` without touching the filesystem.

### Code Execution Sandbox (v4.0.0+)

Amadeus supports both Docker and a lightweight local sandbox. Set `SANDBOX_MODE` in `.env`:

| Mode | Technology | Best For |
|---|---|---|
| `docker` | Ephemeral Containers | High-security, Linux-based production |
| `local` | Multiprocessing | Windows, restricted environments, development |
| `auto` | Auto-detect | Default: prefers Docker, falls back to local |

The local sandbox uses **Restricted Globals** (disabling `__import__`, `open`, `eval`) and runs code in a separate process for isolation.

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
