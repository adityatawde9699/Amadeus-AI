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
| `builder` | Installs locked dependencies (`uv sync --frozen --no-dev`) into `/opt/venv` |
| `artifacts` | Pinned CPU-only torch/transformers/sklearn toolchain (build-time only) that exports the int8 ONNX MiniLM embedder and trains `Model/category_classifier.npz` |
| `runtime` | Production image with the venv, source, `config/` and the two router artifacts; non-root user `amadeus`; ~1.1 GB |

> The runtime image ships core deps only (no `torch`/`transformers`/`scikit-learn`); embedding runs via `onnxruntime`. The first build downloads the embedding checkpoint from Hugging Face.

#### Local LLM (GGUF) in containers

The GGUF model is not in the image by default. There are three ways to provide it:

| Option | How |
|---|---|
| **Download on first start** (compose default) | Compose sets `SLM_MODEL_REPO_ID` / `SLM_MODEL_FILENAME` and `SLM_MODEL_PATH=/app/gguf/<file>`. The file is fetched once into the `gguf` named volume and reused after that. Override the model with those two variables in `.env`. The default, Qwen3-4B, needs about 5 GB RAM; on smaller hosts use Llama-3.2-3B (~4 GB) or 1B (~1.5 GB). See `.env.example`. |
| **Use a model you already have** | Bind-mount its directory instead of the volume, e.g. `./Model:/app/gguf:ro`. |
| **Bake it into the image** | `docker build --build-arg GGUF_REPO_ID=bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF --build-arg GGUF_FILENAME=Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf .` (adds the model size to the image). |

**NVIDIA GPU:** `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build` builds the CUDA variant and reserves the GPU. See [[GPU-Acceleration]].

With plain `docker run` and no build args, no local model is configured. Pass the same `SLM_MODEL_*` variables, or run cloud-only (`LOCAL_ONLY_MODE=false` plus `GROQ_API_KEY`/`GEMINI_API_KEY`).

### Entrypoint

```bash
uvicorn src.transports.fastapi_transport:app --host 0.0.0.0 --port 8000 --workers 1
```

Database migrations are applied on startup by the app itself (`RUN_MIGRATIONS_ON_START=true` for the FastAPI host).

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

`docker-compose.yml` defines `amadeus` (API), `worker` (arq queue), `postgres`, `redis`, `qdrant` and `jaeger`; there is no separate prod profile. Set `POSTGRES_PASSWORD` and `SECRET_KEY` in `.env`, then:

```bash
docker-compose up --build -d
docker-compose logs -f amadeus
```

The API runs **one uvicorn worker** (the Dockerfile `CMD`). Redis and PostgreSQL ports are **not exposed to the host** — internal network only.

### Scaling beyond one worker

By default HITL confirmations, the pre-auth login rate limit and LangGraph checkpoints are per-process / per-host, which is correct for one worker. To run several workers or replicas:

| Setting | Effect |
|---|---|
| `SHARED_STATE_BACKEND=redis` | Pending confirmations and decisions live in Redis (any worker can approve a request another worker is waiting on); the auth rate limit is a shared Redis window. Startup **fails** if Redis is unreachable rather than silently splitting state. slowapi's per-user limits already use Redis when it is reachable. |
| `CHECKPOINT_BACKEND=postgres` | Paused agent runs are checkpointed in Postgres (`CHECKPOINT_POSTGRES_URL`, default `DATABASE_URL`), so a run paused on one worker resumes on another. Requires the `[scale]` extra (`pip install "amadeus-ai[scale]"`, or `docker build --build-arg UV_SYNC_EXTRAS="--extra scale" .`); creates LangGraph's checkpoint tables on first start. |

Still per-process regardless: the local llama.cpp model (each worker loads its own copy — budget RAM accordingly) and the Telegram long-poll transport (run it in exactly one process).

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
