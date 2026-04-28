# Redis Quota Tracking

Daily usage counters are stored in Redis using atomic **`INCR` + `EXPIREAT`** so all workers share a consistent count across horizontal scaling.

---

## Key Schema

| Provider | Redis Key Pattern | Daily Limit | TTL |
|---|---|---|---|
| LlamaCpp | — (local, unlimited) | ∞ | — |
| Ollama | — (local, unlimited) | ∞ | — |
| Groq | `llm_usage:groq:{date}` | 14,400 | 86,400 s |
| Gemini | `llm_usage:gemini:{date}` | 1,500 | 86,400 s |
| OpenAI | `llm_usage:openai:{date}` | 100 | 86,400 s |

`{date}` format: `YYYY-MM-DD` (UTC).

---

## How It Works

```python
# Pseudo-code for each LLM call
key = f"llm_usage:{provider}:{today}"
count = redis.incr(key)
if count == 1:
    redis.expireat(key, end_of_day_utc_timestamp)
if count > DAILY_LIMIT[provider]:
    raise LLMRateLimitError(provider)
```

- **Atomic increments** ensure no double-counting under concurrent load.
- **`EXPIREAT`** is only set on the first call of the day (count == 1), aligning TTL with UTC midnight.

---

## Fallback Behaviour

When **Redis is unavailable**, the router falls back to **in-process counters** that reset on restart. This means:

- Multi-worker deployments may over-consume quota during Redis outages.
- Counters are lost on process restart.

A warning is logged: `Redis unavailable — falling back to in-process quota tracking`.

---

## Cost Alerts

A cost alert is logged when the estimated daily spend exceeds **$0.25**:

```
WARNING: Estimated daily LLM spend ($0.27) has exceeded the $0.25 alert threshold.
```

Costs are estimated using `COST_PER_REQUEST` constants defined in `LLMRouter`.

---

## Viewing Usage

```bash
# Via API (no auth required)
curl http://localhost:8000/api/v1/llm/usage
```

```json
{
  "date": "2026-04-28",
  "providers": {
    "groq": {"used": 1234, "limit": 14400, "remaining": 13166},
    "gemini": {"used": 45, "limit": 1500, "remaining": 1455},
    "openai": {"used": 0, "limit": 100, "remaining": 100}
  }
}
```

---

*← [[API-Reference]] | [[Messaging-Integrations]] →*
