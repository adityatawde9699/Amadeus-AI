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

# 5. Start the server
uv run uvicorn src.api.server:app --reload --host 0.0.0.0 --port 8000
```

Interactive API docs available at `http://localhost:8000/docs` (requires `DEBUG=true`).

---

## Offline / Local-First Mode

Download a GGUF model (e.g., Phi-3 mini) and place it in the `Model/` directory:

```bash
pip install llama-cpp-python
```

Then set in `.env`:
```env
SLM_MODEL_PATH=./Model/phi-3-mini-4k-instruct-q4.gguf
LOCAL_ONLY_MODE=true
```

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
