# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 3.2.x   | ✅ Active support |
| 3.1.x   | ⚠️ Security patches only — upgrade recommended |
| 3.0.x   | ⚠️ Security patches only — please upgrade |
| 2.x     | ❌ End of life |
| 1.x     | ❌ End of life |

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

### API Keys & Secrets
- All API keys are loaded from environment variables — never hardcoded
- `.env.prod`, `.env.staging` are gitignored — never commit real secrets
- `SECRET_KEY` auto-generates a cryptographically-secure 32-byte ephemeral key at startup if not configured — a `WARNING` is logged urging operators to set a persistent value for production (v3.2.1+)
- `IPC_SECRET_TOKEN` is a persistent stable token stored at `data/ipc_secret.token` with `chmod 600`. If the file is missing, empty, corrupt (non-UTF-8), or unreadable, a `CRITICAL` log entry is emitted before regenerating (v3.2.1+)
- `WHATSAPP_APP_SECRET` is required for HMAC-SHA256 verification of WhatsApp webhooks (v3.2.1+)
- `POSTGRES_PASSWORD` must be set in `.env` before production deployment — the default `amadeus_password` is a development placeholder only

### Authentication
- JWT via `fastapi-users` with bcrypt password hashing
- Rate limiting per user (JWT `sub` claim) with IP fallback via `slowapi`; falls back to in-memory storage if Redis is unreachable (v3.2.1+)
- RBAC middleware: `RequireUser` role required for chat/voice/task endpoints
- **SEC-03**: `MASTER_TELEGRAM_CHAT_ID` allowlist — messages from any other Telegram `chat_id` receive `"Unauthorized."` and are dropped before any processing (v3.2.1+)
- **SEC-02**: `X-Hub-Signature-256` HMAC verification on every inbound WhatsApp webhook payload (v3.2.1+)

### Network Isolation (Docker)
- Redis (`6379`) and Postgres (`5432`) ports are **not exposed to the host** — both services are internal to the `amadeus-network` Docker bridge
- The API port (`8000`) is the only port exposed to the host

### Tool Execution (HITL)
- Destructive tool operations (file deletion, app launch) require user confirmation
- Confirmation has a 60-second timeout before auto-deny
- **Filesystem sandboxing (v3.2.1+)**: `copy_file`, `move_file`, and `create_folder` all resolve canonical paths and validate against `SEARCH_ALLOWED_DIRS` via `_assert_in_allowed_dirs()`. Path traversal (e.g. `../../etc/passwd`) returns `"Access denied"` without touching the filesystem.
- Python sandbox execution runs in an ephemeral Docker container with `--network=none`, `--memory=256m`, `--cpus=0.5`

### Prompt Injection (v3.2.1+)
- **SEC-01**: All user task text is wrapped in `<user_task>` XML boundary tags before being inserted into the ReAct prompt. ReAct control tokens (`Action:`, `Thought:`, `Action Input:`, `Observation:`, `FINISH`) found in user input are replaced with `[BLOCKED:TOKEN]` neutralisation markers, preventing LLM-assisted privilege escalation via messaging channels.

### Memory & RAG
- The Flash Memory Cache (L1) is in-process RAM only — never written to disk
- Qdrant stores vector embeddings only — raw message text is stored in the payload
- **Memory deduplication (v3.2.1+)**: Point IDs are content-based `uuid5(session_id:role:text)` — flooding identical messages now occupies one slot instead of N
- Workspace index (`data/workspace_index/`) contains file path metadata and chunk content — gitignored by default

### Local Model Privacy
- When `SLM_MODEL_PATH` is set and `LOCAL_ONLY_MODE=true`, no data leaves the machine
- Ollama and LlamaCpp adapters run entirely locally — no API calls made

### Dependency Auditing
- `pip-audit` runs on every CI push to check for known CVEs in dependencies
- Bandit static security analysis runs at `--severity-level high`
- GitGuardian pre-commit hook scans for leaked secrets before every commit

---

## Known Limitations

- `ALLOW_DEBUG_RESPONSES=true` in production will expose full stack traces to API clients — this is a deliberate developer escape hatch but a **severe security risk in production**. Always set `ALLOW_DEBUG_RESPONSES=false` in production `.env`
- The `S307` (eval) and `S603/S607` (subprocess) bandit/ruff rules are suppressed for the tool execution layer — these usages are intentional, sandboxed, and HITL-gated
- `mktemp()` is used in the Whisper STT pipeline (tracked as tech debt — will be replaced with `NamedTemporaryFile`)
- `assert` statements are used in some production code paths as guards — these are disabled under Python `-O` optimization flag and are tracked for replacement
- The `/api/v1/metrics` Prometheus endpoint is unauthenticated (tracked as SEC-07) — restrict access at the network/proxy layer in production deployments
