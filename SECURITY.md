# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 2.x     | ✅ Active support |
| 1.x     | ❌ End of life — please upgrade |

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
- `SECRET_KEY` is required for JWT authentication in production (`ENV=production`)
- `IPC_SECRET_TOKEN` is generated fresh each process startup (not persisted)

### Authentication
- JWT via `fastapi-users` with bcrypt password hashing
- Rate limiting per user (JWT `sub` claim) with IP fallback via `slowapi`
- RBAC middleware: `RequireUser` role required for chat/voice/task endpoints

### Tool Execution (HITL)
- Destructive tool operations (file deletion, app launch) require user confirmation
- Confirmation has a 60-second timeout before auto-deny
- Filesystem tools are sandboxed to `SEARCH_ALLOWED_DIRS` (default: Documents, Desktop, Downloads)
- `eval()` usage is deliberately restricted to controlled tool execution only (ruff `S307` suppressed with comment)

### Local Model Privacy
- When `SLM_MODEL_PATH` is set and `LOCAL_ONLY_MODE=true`, no data leaves the machine
- Ollama and LlamaCpp adapters run entirely locally — no API calls made

### Dependency Auditing
- `pip-audit` runs on every CI push to check for known CVEs in dependencies
- Bandit static security analysis runs at `--severity-level high`

---

## Known Limitations

- `ALLOW_DEBUG_RESPONSES=true` in production will expose full stack traces to API clients — this is a deliberate developer escape hatch but a severe security risk in production
- The `suspiocus-eval-usage` (S307) and `subprocess-without-shell` (S603) bandit/ruff rules are suppressed for the tool execution layer — these usages are intentional and sandboxed
