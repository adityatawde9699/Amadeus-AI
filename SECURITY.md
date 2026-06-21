# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 6.0.x   | ✅ Active support |
| 5.0.x   | ⚠️ Security patches only — upgrade recommended |
| 4.0.x   | ⚠️ Security patches only — upgrade recommended |
| ≤ 3.2.x | ❌ End of life |

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

### Authorization model — fail closed (v6.0.0+)
- Centralized **Tool Policy Engine** evaluates every tool call before execution.
- Enforces `RiskLevel` (LOW, MEDIUM, HIGH, CRITICAL).
- **Graduated permission profiles** `READ_ONLY < STANDARD < SYSTEM_FULL`, with a
  role mapping (`guest→READ_ONLY`, `user→STANDARD`, `admin→SYSTEM_FULL`). Each
  tool declares a `min_permission`; the engine denies callers whose profile rank
  is below it. `ToolExecutor.execute()` defaults to `READ_ONLY` when no context is
  supplied (no implicit elevation).
- Anonymous API callers are `READ_ONLY`; background work (scheduler, watchers,
  autonomous loop, goal executor) runs at `STANDARD`, not `SYSTEM_FULL`.
- Blocks termination of protected system processes.
- **Note:** the previous shell-argument substring denylist was **removed** — it
  was bypassable and is *not* relied on as an authorization boundary. Privileged
  tools are gated by `min_permission` + confirmation instead.

### Code-execution sandbox — fail closed (v6.0.0+)
- `SANDBOX_MODE` is `Literal["disabled", "docker"]`, default **`disabled`**.
- The in-process `LocalSandboxExecutor` was **removed** (trivially escapable). When
  the sandbox is disabled or Docker is unavailable, `execute_python_script`
  refuses to run code rather than falling back.
- The Docker sandbox is hardened: read-only root FS, all capabilities dropped,
  `no-new-privileges`, PID/memory/swap/CPU limits, networking disabled, non-root
  user, small writable `tmpfs`, pinned image, and an enforced kill timeout.

### Network egress — SSRF protection (v6.0.0+)
- `fetch_webpage_content` validates URLs through an egress guard that resolves the
  host to *all* its addresses and rejects any non-public one (loopback, RFC1918,
  link-local incl. cloud metadata `169.254.169.254`, multicast, reserved,
  IPv4-mapped IPv6). Only `http`/`https` are allowed.
- Every redirect hop is re-validated; the body is capped at 2 MiB; DNS resolves
  off the event loop with a fail-closed timeout. `ALLOW_PRIVATE_NETWORK_FETCH` is
  a development-only escape hatch, forced off in production.

### Plugin management (v6.0.0+)
- `manage_plugins` is administrator-only (`SYSTEM_FULL`) and confirmation-gated.
- Plugin names are containment-checked (no path traversal); newly written plugins
  are **not** imported/executed in the same request (loaded on restart) so a
  single tool call cannot author *and* run arbitrary code.

### API Keys & Secrets
- All API keys are loaded from environment variables — never hardcoded.
- `.env` / `.env.*` are gitignored and excluded from the Docker image — never
  commit real secrets.
- `SECRET_KEY` auto-generates a cryptographically-secure 32-byte ephemeral key at
  startup if not configured.
- `IPC_SECRET_TOKEN` is a persistent stable token stored at
  `data/ipc_secret.token` with `chmod 600`.
- Password-reset and verification tokens are **never logged** (DEBUG-only in
  development); they are delivered to the user out-of-band.

### Authentication & abuse prevention
- JWT via `fastapi-users` with bcrypt password hashing.
- RBAC middleware: `RequireUser` required for chat/task endpoints; `/chat/clear`
  is authenticated and scoped to the caller's session.
- Public registration cannot set `role`/`tenant_id` (no self-service privilege
  escalation); new users default to `GUEST`.
- `MASTER_TELEGRAM_CHAT_ID` allowlist is **fail closed**: an unset/invalid
  allowlist rejects all senders and refuses to start polling.
- **Per-IP pre-auth rate limiting** on login/register/forgot/reset/verify blunts
  credential stuffing and enumeration (configurable via `RATE_LIMIT_*`).

### Network Isolation (Docker)
- Postgres (`5432`), Redis (`6379`), and Qdrant (`6333/6334`) publish **no host
  ports** — reachable only on the internal compose network by service name.
- The API and the Jaeger UI bind to loopback (`127.0.0.1`); place a TLS reverse
  proxy in front for external access. Jaeger OTLP ingest stays internal.

### Prompt Injection (v3.2.1+)
- **SEC-01**: User task text wrapped in `<user_task>` XML boundary tags. ReAct
  control tokens found in user input are neutralized with `[BLOCKED:TOKEN]`.

### Supply chain & dependency auditing
- The Docker image is built from the pinned lockfile (`uv sync --frozen`) — the
  same set CI and `pip-audit` vet — so deployed images match tested versions.
- `pip-audit` runs on every CI push to check for known CVEs.
- Bandit static security analysis runs at `--severity-level high`.
- GitGuardian pre-commit hook scans for leaked secrets.

---

## Known Limitations

- `ALLOW_DEBUG_RESPONSES=true` in production will expose full stack traces to API clients — this is a deliberate developer escape hatch but a **severe security risk in production**. Always set `ALLOW_DEBUG_RESPONSES=false` in production `.env`
- The `S603/S607` (subprocess) bandit/ruff rules are suppressed for the tool execution layer — these usages are intentional and HITL-gated; arbitrary Python runs only inside the hardened Docker sandbox (or is refused)
- `assert` statements are used in some production code paths as guards — these are disabled under Python `-O` optimization flag and are tracked for replacement
- The `/api/v1/metrics` Prometheus endpoint is unauthenticated (tracked as SEC-07) — restrict access at the network/proxy layer in production deployments
- The SSRF egress guard validates the host, then connects — a small validate-then-connect TOCTOU / DNS-rebind window remains. Full closure requires pinning the validated IP into the connection (tracked follow-up)
- `uv.lock` currently pins a yanked transitive `grpcio==1.78.1` (via the OTLP exporter); a pin/upgrade is a tracked follow-up
- Container base images are pinned by tag, not digest — pin by `@sha256:` digest for full supply-chain reproducibility in production
