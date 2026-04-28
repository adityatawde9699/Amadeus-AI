# Deployment

Three supported deployment targets: **Railway** (managed cloud), **Docker Compose** (self-hosted), and **Windows Daemon** (local service).

---

## Railway *(Recommended for Cloud)*

### Automated Deploy (CI/CD)

Merge a PR into `develop` to trigger a Railway staging deploy via GitHub Actions.

> **Requires:** `RAILWAY_TOKEN` set in GitHub repository secrets.

### Manual Deploy

```bash
npm install -g @railway/cli
railway login
railway link
railway up
```

### Required Environment Variables

Set these in the Railway dashboard:

| Variable | Notes |
|---|---|
| `SECRET_KEY` | Generate with `openssl rand -hex 32` |
| `GROQ_API_KEY` | Free — 14,400 req/day |
| `GEMINI_API_KEY` | Free — 1,500 req/day |
| `DATABASE_URL` | Use Railway PostgreSQL plugin |
| `REDIS_URL` | Use Railway Redis plugin |
| `ENV` | `production` |
| `DEBUG` | `false` |

### Dockerfile Stages

The Dockerfile uses a **3-stage multi-stage build:**

| Stage | Purpose |
|---|---|
| `builder` | Installs Python dependencies |
| `model_cache` | Pre-bakes `faster-whisper small` model (~460 MB) — eliminates cold-start |
| `runtime` | Minimal production image, non-root user `amadeus` |

### Entrypoint

```bash
alembic upgrade head && uvicorn src.api.server:app --host 0.0.0.0 --port $PORT
```

Migrations run automatically before each deploy.

---

## Docker Compose *(Self-Hosted)*

### Development

```bash
docker-compose up --build
# API available at http://localhost:8000
# Interactive docs at http://localhost:8000/docs
```

### Production

```bash
# Set POSTGRES_PASSWORD and SECRET_KEY in .env first
docker-compose --profile prod up --build -d

# View logs
docker-compose logs -f api-prod

# Stop
docker-compose --profile prod down
```

The production profile runs **Gunicorn with 4 Uvicorn workers** with resource limits:
- CPU: 2 cores
- Memory: 1 GB

Redis and PostgreSQL ports are **not exposed to the host** — internal network only.

### Service Graph

```
amadeus-network (bridge)
├── api-prod          (port 8000 exposed)
├── postgres          (port 5432 — internal only)
└── redis             (port 6379 — internal only)
```

---

## Windows Daemon

### Option 1 — Build a Binary

```bash
python scripts/build_backend_binary.py
# or
python scripts/build_windows.py
```

### Option 2 — Install as a Windows Service

Run **PowerShell as Administrator:**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows_service.ps1
```

- Uses **NSSM** (auto-downloaded if not present)
- Service auto-starts on boot
- Logs written to `data\logs\`

### Option 3 — Run Directly

```bat
Start_Amadeus.bat
```

### Windows-Only Features

The following tools require `pywin32` and only function on Windows:

- `send_outlook_email`
- `read_outlook_emails`
- `create_excel_spreadsheet`
- `create_word_document`

---

*← [[Security-Model]] | [[Development-Guide]] →*
