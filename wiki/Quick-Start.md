# Quick Start

Get Amadeus running in under 10 minutes.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | Required |
| `uv` package manager | Latest | Recommended; or use `pip` |
| Docker Desktop | Latest | For containerised setup or sandboxed code execution |
| PostgreSQL | 15+ | Production; SQLite is the default for development |
| Redis | 5+ | Caching and rate limiting |
| LLM API key **or** local GGUF model | — | At least one required |

---

## Local Installation

```bash
# 1. Clone the repository
git clone https://github.com/adityatawde9699/Amadeus-AI.git
cd Amadeus-AI

# 2. Install dependencies
uv sync --all-extras --dev
# or: pip install -e ".[all]"

# 3. Configure environment
cp .env.example .env
# Edit .env — at minimum set GROQ_API_KEY and SECRET_KEY

# 4. Run database migrations
uv run alembic upgrade head

# 5. Start the server (API host)
uv run python -m src.transports.fastapi_transport
# or run the ASGI app directly with reload for development:
# uv run uvicorn src.transports.fastapi_transport:app --reload --host 0.0.0.0 --port 8000
```

Interactive API docs available at `http://localhost:8000/docs` (requires `DEBUG=true`).

> **Telegram-first daemon:** for local/desktop use, run `uv run amadeus-daemon` instead
> (requires `TELEGRAM_BOT_TOKEN` and `MASTER_TELEGRAM_CHAT_ID`). It runs headless with no FastAPI host.

---

## Offline / Local-First Mode

`llama-cpp-python` is a core dependency. With `MODEL_DOWNLOAD_ENABLED=true` (the default), the model named in `.env` is downloaded into `Model/` on first start:

```env
SLM_MODEL_REPO_ID=bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF
SLM_MODEL_FILENAME=Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf
LOCAL_ONLY_MODE=true
```

Qwen3-4B is the default. It scored 100% on the agent tool-selection eval and needs about 5 GB RAM. On smaller machines use Llama-3.2-3B (86%, about 4 GB) or Llama-3.2-1B (68%, about 1.5 GB). The full table is in `.env.example` and `evals/results/agent-models.md`. To use a file you already have, set `SLM_MODEL_PATH=/absolute/path/model.gguf` instead.

**GPU:** a plain install runs on CPU, except on macOS, where Metal is used. With an NVIDIA, AMD or Vulkan GPU, run `scripts/install_gpu_backend.sh` once. Amadeus then offloads to the GPU automatically, which is about 15× faster. See [[GPU-Acceleration]].

---

## Build the Workspace Search Index *(optional)*

Enables the `search_workspace` tool over your local files:

```bash
python scripts/index_workspace.py --root "C:\Users\ASUS\Downloads" --max-chunks 15000

# Subsequent runs are incremental — only changed files are re-embedded
```

---

## Docker (Development)

```bash
docker-compose up --build
# API available at http://localhost:8000
# Interactive docs at http://localhost:8000/docs
```

---

## Docker (Production)

```bash
# Set POSTGRES_PASSWORD and SECRET_KEY in .env first
docker-compose --profile prod up --build -d

# View logs
docker-compose logs -f api-prod
```

The production profile runs **Gunicorn with 4 Uvicorn workers** (2 CPU / 1 GB RAM limit). Redis and PostgreSQL ports are **not exposed to the host** — they remain internal to the Docker bridge network.

> **Windows shortcut:** Run `Setup_Amadeus.bat` for guided first-time setup with auto-generated `SECRET_KEY`.

---

## Generate a Test JWT

```python
import jwt, datetime

payload = {
    "sub": "admin",
    "iat": datetime.datetime.utcnow(),
    "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24),
}
token = jwt.encode(payload, "your-secret-key", algorithm="HS256")
print(token)
```

Use the token in all protected API calls:
```
Authorization: Bearer <token>
```

---

*← [[Home]] | [[Configuration-Reference]] →*
