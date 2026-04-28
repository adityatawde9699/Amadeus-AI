# Security Model

Amadeus is designed with defence-in-depth across authentication, network isolation, secret management, and tool execution safety.

---

## Authentication

| Aspect | Implementation |
|---|---|
| Algorithm | JWT HS256 via `python-jose` |
| `exp` claim | Required in production; accepted without `exp` in development |
| Rate limiting | Keyed by `sub` (user ID); falls back to IP for unauthenticated requests (SlowAPI) |
| RBAC | `admin` / `user` / `guest` roles enforced per route |

**Guest-tier users** are placed in `READ_ONLY` profile — all `requires_confirmation=True` tools are hard-blocked regardless of any callback override.

---

## Network Isolation (Docker)

| Port | Exposed to Host? |
|---|---|
| `6379` (Redis) | ❌ Internal only |
| `5432` (PostgreSQL) | ❌ Internal only |
| `8000` (API) | ✅ Exposed |

Both data services are internal to the `amadeus-network` Docker bridge. There is no route from the internet to Redis or PostgreSQL without going through the application layer.

---

## Secret Management

- All API keys loaded from environment variables — **never hardcoded**.
- `.env.prod`, `.env.staging`, `.env.local` are in `.gitignore`.
- **GitGuardian pre-commit hook** scans for leaked secrets before every commit.
- `SECRET_KEY` is auto-generated on first run via `Setup_Amadeus.bat`.

---

## Tool Execution Safety

### HITL Confirmation

Destructive tools require explicit approval with a **60-second timeout** (auto-deny on timeout):

```
terminate_program · delete_file · execute_python_script
fs_write_file · send_outlook_email · send_email · send_slack_message
```

### Filesystem Sandboxing

- `search_file` is restricted to `SEARCH_ALLOWED_DIRS` (configurable in `.env`).
- Filesystem tools (`fs_*`) are sandboxed to `DATA_DIR/agent_workspace/`.
- Path traversal attempts are blocked at the `_safe_resolve()` level.

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

## Observability & Audit

| Aspect | Detail |
|---|---|
| Log format | JSON via `structlog` |
| Request tracing | `request_id` UUID attached to every request; returned as `X-Request-ID` header |
| Sensitive data | API keys, raw prompts, auth tokens are **never logged** (OWASP-hardened) |
| Log files | `data/logs/amadeus.log` (rotating, 10 MB, 5 backups) |
| Security scan | `bandit -r src/ -ll` — **0 HIGH findings** enforced in CI |
| CVE audit | `pip-audit` — **0 actionable HIGH CVEs** |

---

## Reporting Vulnerabilities

See [SECURITY.md](https://github.com/adityatawde9699/Amadeus-AI/blob/main/SECURITY.md) for the responsible disclosure process.

---

*← [[Messaging-Integrations]] | [[Deployment]] →*
