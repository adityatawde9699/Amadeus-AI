# Configuration Reference

All settings are loaded from `.env` via **Pydantic-settings**. See `.env.example` for the full annotated list.

---

## Required Variables

| Variable | Description | Example |
|---|---|---|
| `SECRET_KEY` | JWT signing secret (HS256). Auto-generates an ephemeral key at startup if not set (v3.2.1+) — set a persistent value for production. | `openssl rand -hex 32` |
| `DATABASE_URL` | SQLAlchemy connection string | `postgresql+asyncpg://postgres:pass@localhost:5432/amadeus` |
| `REDIS_URL` | Redis connection URL (rate limiting + quota tracking) | `redis://localhost:6379/0` |

> **Tip:** Run `Setup_Amadeus.bat` on Windows to auto-generate a secure `SECRET_KEY`.

---

## LLM Providers

Configure **at least one**. Priority order: LlamaCpp → Ollama → Groq → Gemini → OpenAI.

| Variable | Provider | Free? | Notes |
|---|---|---|---|
| `SLM_MODEL_PATH` | LlamaCpp (local GGUF) | ✅ Unlimited | Path to `.gguf` file |
| `OLLAMA_MODEL` | Ollama (local server) | ✅ Unlimited | e.g. `llama3.2` |
| `OLLAMA_ENABLED` | Enable/disable Ollama | — | `true` / `false` |
| `GROQ_API_KEY` | Groq — Llama 3.3 70B | ✅ 14,400 req/day | Free tier |
| `GEMINI_API_KEY` | Gemini 2.5 Flash | ✅ 1,500 req/day | Free tier |
| `OPENAI_API_KEY` | GPT-4o-mini | ❌ Paid | Emergency fallback |

### Local-Only Mode

Disable all cloud providers entirely:

```env
LOCAL_ONLY_MODE=true
```

---

## Core Settings

| Variable | Default | Description |
|---|---|---|
| `ENV` | `development` | `development` or `production` |
| `DEBUG` | `false` | Enables `/docs` Swagger UI |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Server port |
| `DATA_DIR` | `./data` | Base data directory |

---

## Optional Integrations

| Variable | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Enable Telegram long-polling |
| `MASTER_TELEGRAM_CHAT_ID` | **Authorization allowlist** (v3.2.1+) — comma-separated `chat_id` values permitted to command Amadeus. Messages from any other ID receive `"Unauthorized."` |
| `WHATSAPP_ACCESS_TOKEN` | WhatsApp Cloud API token |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp sender phone number ID |
| `WHATSAPP_VERIFY_TOKEN` | Meta webhook challenge verification token |
| `WHATSAPP_APP_SECRET` | **Required for HMAC verification (v3.2.1+)** — Meta App Secret. Forged webhook payloads return 403. |
| `EMAIL_ADDRESS` | IMAP read + SMTP send address |
| `EMAIL_APP_PASSWORD` | Gmail App Password or SMTP password |
| `EMAIL_IMAP_SERVER` | IMAP server (e.g. `imap.gmail.com`) |
| `EMAIL_SMTP_SERVER` | SMTP server (e.g. `smtp.gmail.com`) |
| `EMAIL_SMTP_PORT` | SMTP port (e.g. `587`) |
| `WEATHER_API_KEY` | OpenWeatherMap — `get_weather` tool |
| `DEFAULT_LOCATION` | Default city for `get_weather` when no location specified (v3.2.1+) — replaces hardcoded `"India"` |
| `NEWS_API_KEY` | NewsAPI — `get_news` tool |
| `TAVILY_API_KEY` | Deep web search fallback |
| `SENTRY_DSN` | Error monitoring (optional) |
| `TURBOVEC_ENABLED` | Toggle Turbovec memory service (default: true) |
| `MEMORY_ENABLED` | Enable/disable long-term semantic memory |
| `SEARCH_ALLOWED_DIRS` | Comma-separated dirs for `search_file`, `copy_file`, `move_file`, `create_folder` (v3.2.1+) |
| `PROACTIVE_CHECK_INTERVAL_MINUTES` | APScheduler interval for proactive loop (default `30`) |

---

## Voice Settings

| Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `small` | faster-whisper model size |
| `WHISPER_DEVICE` | `cpu` | `cpu` or `cuda` |
| `TTS_VOICE` | `en-US-JennyNeural` | Edge TTS voice |

---

*← [[Quick-Start]] | [[Core-Systems]] →*
