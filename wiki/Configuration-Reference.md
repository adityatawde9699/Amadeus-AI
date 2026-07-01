# Configuration Reference

All settings are loaded from `.env` via **Pydantic-settings**. See `.env.example` for the full annotated list.

---

## Required Variables

| Variable | Description | Example |
|---|---|---|
| `SECRET_KEY` | JWT signing secret (HS256). Auto-generates an ephemeral key at startup if not set (v6.0.0+) — set a persistent value for production. | `openssl rand -hex 32` |
| `DATABASE_URL` | SQLAlchemy connection string | `postgresql+asyncpg://postgres:pass@localhost:5432/amadeus` |
| `REDIS_URL` | Redis connection URL (rate limiting + quota tracking) | `redis://localhost:6379/0` |

> **Tip:** Run `Setup_Amadeus.bat` on Windows to auto-generate a secure `SECRET_KEY`.

---

## LLM Providers

Configure **at least one**. Priority order: LlamaCpp → Groq → Gemini.

| Variable | Provider | Free? | Notes |
|---|---|---|---|
| `SLM_MODEL_PATH` | LlamaCpp (local GGUF) | ✅ Unlimited | Absolute path to `.gguf` file (takes priority) |
| `SLM_MODEL_REPO_ID` / `SLM_MODEL_FILENAME` | LlamaCpp (auto-download) | ✅ Unlimited | HuggingFace repo + filename; fetched into `Model/` when `SLM_MODEL_PATH` is unset |
| `GROQ_API_KEY` | Groq — `llama-3.3-70b-versatile` | ✅ 14,400 req/day | Free tier (`GROQ_MODEL` overrides) |
| `GEMINI_API_KEY` | Gemini — `gemini-3-flash-preview` | ✅ 1,500 req/day | Free tier (`GEMINI_MODEL` overrides) |

> Only these three providers are wired into `LLMRouter`. There is no Ollama or OpenAI adapter in the current codebase.

### Local-Only Mode

`LOCAL_ONLY_MODE` **defaults to `true`** — out of the box only local providers are used and Groq/Gemini are skipped even if keys are set. Set it to `false` to enable the cloud fallback chain:

```env
LOCAL_ONLY_MODE=false   # allow Groq / Gemini fallback
```

---

## Core Settings

| Variable | Default | Description |
|---|---|---|
| `ENV` | `development` | `development`, `staging`, or `production` |
| `DEBUG` | `false` | Enables `/docs` Swagger UI |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `API_HOST` | `127.0.0.1` | Server bind address (loopback by default) |
| `API_PORT` | `8765` | Server port (Docker Compose maps the container to `8000`) |
| `DATA_DIR` | `./data` | Base data directory |

---

## Optional Integrations

| Variable | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Enable Telegram long-polling |
| `MASTER_TELEGRAM_CHAT_ID` | **Authorization allowlist** (v6.0.0+) — comma-separated `chat_id` values permitted to command Amadeus. Messages from any other ID receive `"Unauthorized."` |
| `TELEGRAM_ELEVATED_CHAT_IDS` | Subset of allowlisted chat IDs granted the `SYSTEM_FULL` profile (host/destructive tools). Empty = no Telegram user gets full access. |
| `EMAIL_ADDRESS` | IMAP read + SMTP send address |
| `EMAIL_APP_PASSWORD` | Gmail App Password or SMTP password |
| `EMAIL_IMAP_SERVER` | IMAP server (e.g. `imap.gmail.com`) |
| `EMAIL_SMTP_SERVER` | SMTP server (e.g. `smtp.gmail.com`) |
| `EMAIL_SMTP_PORT` | SMTP port (e.g. `587`) |
| `WEATHER_API_KEY` | OpenWeatherMap — `get_weather` tool |
| `DEFAULT_LOCATION` | Default city for `get_weather` when no location specified (v6.0.0+) — replaces hardcoded `"India"` |
| `NEWS_API_KEY` | NewsAPI — `get_news` tool |
| `TAVILY_API_KEY` | Deep web search fallback |
| `SENTRY_DSN` | Error monitoring (optional) |
| `MEMORY_ENABLED` | Enable/disable long-term semantic (Turbovec) memory (default: true) |
| `SEARCH_ALLOWED_DIRS` | Comma-separated dirs for `search_file`, `copy_file`, `move_file`, `create_folder` (v6.0.0+) |
| `PROACTIVE_CHECK_INTERVAL_MINUTES` | APScheduler interval for proactive loop (default `30`) |

---

*← [[Quick-Start]] | [[Core-Systems]] →*
