# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 4.0.x   | ✅ Active support |
| 3.2.x   | ⚠️ Security patches only — upgrade recommended |
| 3.1.x   | ❌ End of life |
| 2.x     | ❌ End of life |

---

## Reporting a Vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.**

Disclosing security issues publicly before a fix is available puts all users at risk.

### Steps to Report

1. **Email:** Send details to `adityatawde9699@gmail.com` with the subject line:
   ```
   [SECURITY] Amadeus-AI — <brief description>
   ```

2. **Include in your report:**
   - A clear description of the vulnerability
   - Steps to reproduce (proof-of-concept code if possible)
   - Affected version(s)
   - Potential impact assessment
   - Your suggested fix (optional but appreciated)

3. **Response timeline:**
   - **Acknowledgement:** within 48 hours
   - **Initial assessment:** within 5 business days
   - **Fix & disclosure:** coordinated with you, targeting within 30 days for critical issues

4. **Credit:** With your permission, we will acknowledge your contribution in the release notes and CHANGELOG.

---

## Security Design Notes

### Tool Policy Engine (v4.0.0+)
- Centralized gatekeeper that evaluates every tool call before execution
- Enforces `RiskLevel` (LOW, MEDIUM, HIGH, CRITICAL)
- Enforces `PermissionProfile` (READ_ONLY sessions are blocked from mutating or high-risk tools)
- Blocks termination of protected system processes
- Sanitizes shell command arguments for forbidden tokens

### Multi-Sandbox Execution (v4.0.0+)
- **Docker Sandbox**: Ephemeral container with no network access, memory limits, and non-root user
- **Local Sandbox**: Multiprocessing-based isolation with restricted globals (`__import__`, `open`, `eval` disabled)
- Auto-detects Docker availability and falls back to local sandbox gracefully

### API Keys & Secrets
- All API keys are loaded from environment variables — never hardcoded
- `.env.prod`, `.env.staging` are gitignored — never commit real secrets
- `SECRET_KEY` auto-generates a cryptographically-secure 32-byte ephemeral key at startup if not configured
- `IPC_SECRET_TOKEN` is a persistent stable token stored at `data/ipc_secret.token` with `chmod 600`.

### Authentication
- JWT via `fastapi-users` with bcrypt password hashing
- RBAC middleware: `RequireUser` role required for chat/task endpoints
- **SEC-03**: `MASTER_TELEGRAM_CHAT_ID` allowlist — unauthorized Telegram senders are dropped
- **SEC-02**: `X-Hub-Signature-256` HMAC verification on WhatsApp webhooks

### Network Isolation (Docker)
- Redis (`6379`) and Postgres (`5432`) ports are **not exposed to the host**
- The API port (`8000`) is the only port exposed to the host

### Prompt Injection (v3.2.1+)
- **SEC-01**: User task text wrapped in `<user_task>` XML boundary tags. ReAct control tokens found in user input are neutralized with `[BLOCKED:TOKEN]` markers.

### Dependency Auditing
- `pip-audit` runs on every CI push to check for known CVEs
- Bandit static security analysis runs at `--severity-level high`
- GitGuardian pre-commit hook scans for leaked secrets

---

## Known Limitations

- `ALLOW_DEBUG_RESPONSES=true` in production will expose full stack traces to API clients — this is a deliberate developer escape hatch but a **severe security risk in production**. Always set `ALLOW_DEBUG_RESPONSES=false` in production `.env`
- The `S307` (eval) and `S603/S607` (subprocess) bandit/ruff rules are suppressed for the tool execution layer — these usages are intentional, sandboxed, and HITL-gated
- `mktemp()` is used in the Whisper STT pipeline (tracked as tech debt — will be replaced with `NamedTemporaryFile`)
- `assert` statements are used in some production code paths as guards — these are disabled under Python `-O` optimization flag and are tracked for replacement
- The `/api/v1/metrics` Prometheus endpoint is unauthenticated (tracked as SEC-07) — restrict access at the network/proxy layer in production deployments
