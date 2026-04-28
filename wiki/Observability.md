# Observability

Amadeus exposes structured logs, Prometheus metrics, and optional Sentry error tracking.

---

## Prometheus Metrics

**Endpoint:** `GET /api/v1/metrics` *(no auth required)*

| Metric | Type | Labels | Description |
|---|---|---|---|
| `amadeus_llm_calls_total` | Counter | `provider` | LLM calls per provider |
| `amadeus_tool_calls_total` | Counter | `tool_name` | Tool invocations |
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

## Health Endpoints

```bash
# Liveness probe (load balancer / Railway)
GET /health
# {"status": "ok"}

# Detailed status (DB + Redis + classifier)
GET /api/v1/health/detailed
# {
#   "status": "healthy",
#   "database": "connected",
#   "redis": "connected",
#   "classifier_enabled": true,
#   "llm_providers": ["groq", "gemini"]
# }
```

---

## Sentry

Set `SENTRY_DSN` in `.env` to enable automatic error capture:

```env
SENTRY_DSN=https://xxx@sentry.io/xxx
```

The integration captures:
- Unhandled exceptions with FastAPI request context
- Configurable `traces_sample_rate` for performance monitoring

---

## Grafana *(Planned)*

A Grafana dashboard for Prometheus cost gauges is on the roadmap. See [[Known-Limitations-and-Roadmap]].

---

*← [[Development-Guide]] | [[Known-Limitations-and-Roadmap]] →*
