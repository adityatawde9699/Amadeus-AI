# Observability

Amadeus exposes structured logs, Prometheus metrics, health probes, and optional Sentry error tracking.

---

## Prometheus Metrics

**Endpoint:** `GET /api/v1/metrics` *(no auth required)*

| Metric | Type | Labels | Description |
|---|---|---|---|
| `amadeus_llm_calls_total` | Counter | `provider` | LLM calls per provider |
| `amadeus_tool_calls_total` | Counter | `tool_name` | Tool invocations |
| `amadeus_tool_duration_seconds` | Histogram | `tool_name`, `success` | Per-tool execution latency (10 buckets: 0.01s–30s) |
| `amadeus_tool_executions_total` | Counter | `tool_name`, `result` | Per-tool result breakdown (`success`/`failure`/`timeout`/`denied`) |
| `amadeus_memory_errors_total` | Counter | `operation` | Turbovec upsert/search failures (`upsert`/`search`) |
| `amadeus_cache_hit_rate` | Gauge | — | Cache hit % (updated on every hit) |
| `amadeus_llm_cost_usd` | Gauge | — | Estimated cumulative LLM spend |
| HTTP latency histograms | Histogram | `path`, `method`, `status` | P50/P95/P99 per route |

HTTP metrics are provided by `prometheus-fastapi-instrumentator`.

### Scrape Config (Prometheus)

```yaml
scrape_configs:
  - job_name: amadeus
    static_configs:
      - targets: ["localhost:8000"]
    metrics_path: /api/v1/metrics
```

---

## Health Endpoints

### Liveness Probe

```bash
GET /api/v1/health/live
# → 200 {"status": "alive"}
```

Always returns 200 while the process is running. Used by container orchestrators (Kubernetes, Docker Compose) to detect process crashes.

### Readiness Probe (v6.0.0+)

```bash
GET /api/v1/health/ready
# → 200 {"status": "ready", "checks": {"database": true, "redis": true, "turbovec": true, "llm_provider": true}}
# → 503 {"detail": {"checks": {"database": false, ...}, "details": {"database": "..."}}}
```

Checks all critical dependencies before accepting traffic. Returns **503** with a per-dependency map if any dependency is unhealthy.

| Dependency | Check Method |
|---|---|
| `database` | `SELECT 1` via SQLAlchemy async session |
| `redis` | `await r.ping()` with 2-second timeout |
| `turbovec` | `get_memory_count()` via `TurbovecMemoryService` |
| `llm_provider` | `global_container.llm_router()` accessible |

### Legacy Health Check

```bash
GET /health
# → {"status": "healthy", "service": "Amadeus", "version": "6.0.0", "environment": "production"}
```

---

## Structured Logging

All logs are **JSON-formatted** via `structlog`. The audit middleware attaches a `request_id` UUID to every request.

### Response Headers

Every response includes:

| Header | Value |
|---|---|
| `X-Request-ID` | UUID for the request (use for log correlation) |
| `X-Process-Time` | Wall-clock processing time in seconds |

### Log Files

| Location | Rotation | Backups |
|---|---|---|
| `data/logs/amadeus.log` | 10 MB | 5 files |

### What Is Never Logged

Per OWASP guidelines:
- API keys
- Raw user prompts
- Auth tokens / JWTs
- Database credentials

---

## Sentry

Set `SENTRY_DSN` in `.env` to enable automatic error capture:

```env
SENTRY_DSN=https://xxx@sentry.io/xxx
```

The integration captures:
- Unhandled exceptions with FastAPI request context
- Configurable `traces_sample_rate` for performance monitoring
- `send_default_pii=False` — no user PII leaked to Sentry

---

## Grafana *(Planned)*

A Grafana dashboard for Prometheus cost gauges is on the roadmap. See [[Known-Limitations-and-Roadmap]].

---

*← [[Development-Guide]] | [[Known-Limitations-and-Roadmap]] →*
