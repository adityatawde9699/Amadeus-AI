# API Reference

**Base path:** `/api/v1`  
**Interactive docs:** `http://localhost:8000/docs` *(requires `DEBUG=true`)*

---

## Authentication

All protected routes require a **JWT Bearer token** in the `Authorization` header:

```
Authorization: Bearer <token>
```

Tokens are HS256-signed with `SECRET_KEY`. In production (`ENV=production`), the `exp` claim is required.

### Generate a Test Token

```python
import jwt, datetime

payload = {
    "sub": "admin",
    "iat": datetime.datetime.utcnow(),
    "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24),
}
token = jwt.encode(payload, "your-secret-key", algorithm="HS256")
```

### RBAC Roles

| Role | Access |
|---|---|
| `admin` | All endpoints including system admin routes |
| `user` | Chat, voice, tasks, messaging |
| `guest` | READ_ONLY profile — destructive tools are hard-blocked |

---

## Chat Endpoints

### `POST /api/v1/chat`

Send a message and receive a synchronous response.

**Request:**
```json
{
  "message": "What is the weather in Delhi?",
  "source": "api",
  "session_id": "optional-session-uuid",
  "request_id": "optional-idempotency-key"
}
```

**Response:**
```json
{
  "response": "The weather in Delhi: Haze. Temperature is 31.5°C (feels like 36.2°C). Humidity is 72%.",
  "source": "api",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "tools_used": ["get_weather"]
}
```

---

### `GET /api/v1/chat/stream`

Server-Sent Events streaming — native Gemini `stream=True` or word-by-word fallback.

**Query params:** `message` (required), `session_id` (optional), `source` (default `"api"`)

```bash
curl -N \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/chat/stream?message=Tell+me+a+joke"

# Streams:
# data: {"delta": "Why"}
# data: {"delta": " do"}
# data: {"delta": " programmers ..."}
# data: [DONE]
```

---

### `GET /api/v1/chat/history`

Retrieve conversation history for a session.

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/chat/history?session_id=<SESSION_ID>"
```

---

### `POST /api/v1/chat/clear`

Clear conversation history from both Redis cache and PostgreSQL for the current session.

---

### `GET /api/v1/chat/tools`

Returns all registered tools grouped by category.

---

## Voice WebSocket

```
WS /api/v1/ws/voice
```

Pass the JWT token as a query parameter or in the upgrade headers.

### Protocol (per turn)

| Step | Direction | Payload |
|---|---|---|
| 1 | Client → Server | Raw audio bytes (PCM / WAV chunk) |
| 2 | Server → Client | `{"type": "transcription", "text": "..."}` |
| 3 | Server → Client | `{"type": "response_text", "text": "..."}` |
| 4 | Server → Client | Binary audio bytes (MP3, Edge TTS) |

### Python Client Example

```python
import asyncio, websockets

async def voice_session():
    uri = "ws://localhost:8000/api/v1/ws/voice"
    headers = {"Authorization": "Bearer YOUR_TOKEN"}
    async with websockets.connect(uri, additional_headers=headers) as ws:
        with open("audio.wav", "rb") as f:
            await ws.send(f.read())
        transcript = await ws.recv()   # JSON
        response   = await ws.recv()   # JSON
        audio      = await ws.recv()   # bytes

asyncio.run(voice_session())
```

---

## Messaging

### `POST /api/v1/messaging/send`

Unified outbound dispatch (Telegram, WhatsApp, Email):

```json
{
  "channel": "telegram",
  "to": "123456789",
  "message": "Hello from Amadeus!",
  "subject": null
}
```

### `GET /api/v1/messaging/status`

```json
{"telegram": true, "whatsapp": false, "email": true}
```

### Webhook Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/webhooks/telegram` | Inbound Telegram updates (secret token validated) |
| `GET` | `/api/v1/webhooks/whatsapp` | Meta hub challenge verification |
| `POST` | `/api/v1/webhooks/whatsapp` | Inbound WhatsApp messages |

---

## Tasks

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/tasks` | Create task — body: `{"content": "..."}` |
| `GET` | `/api/v1/tasks` | List tasks — `?status_filter=pending&limit=100` |
| `GET` | `/api/v1/tasks/{id}` | Get task by ID |
| `PATCH` | `/api/v1/tasks/{id}/complete` | Mark complete |
| `DELETE` | `/api/v1/tasks/{id}` | Delete task |
| `GET` | `/api/v1/tasks/summary` | `{"total": N, "pending": N, "completed": N}` |

---

## Health & Observability

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | ❌ | Liveness probe (load balancer / Railway) |
| `GET` | `/api/v1/health/detailed` | ❌ | DB, Redis, classifier status |
| `GET` | `/api/v1/llm/usage` | ❌ | Daily quota report per provider |
| `GET` | `/api/v1/metrics` | ❌ | Prometheus metrics |

### Detailed Health Response

```json
{
  "status": "healthy",
  "database": "connected",
  "redis": "connected",
  "classifier_enabled": true,
  "llm_providers": ["groq", "gemini"]
}
```

---

## HITL Confirmation

### `POST /api/v1/confirm/{request_id}`

Approve or deny a pending HITL confirmation from the API layer:

```json
{"approved": true}
```

Requests time out after **60 seconds** → auto-deny.

---

*← [[Tool-Registry]] | [[Redis-Quota-Tracking]] →*
