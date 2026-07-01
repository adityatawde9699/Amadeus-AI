# Messaging Integrations

Amadeus supports two messaging channels: **Telegram** and **Email**.

---

## Telegram

Amadeus uses `python-telegram-bot` v20+ in **long-polling mode** — no webhooks or public URL required.

### Setup

1. Create a bot via `@BotFather` on Telegram and copy the token.
2. Add to `.env`:
   ```env
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   ```
3. The polling loop starts automatically in the FastAPI lifespan — no extra process needed.

### How It Works

- Each Telegram message spawns an isolated `AmadeusService` session keyed by `chat_id`.
- A `TelegramConfirmationCallback` presents **inline keyboard buttons** for HITL approvals.
- The full tool registry is available via natural language in the chat.

### Proactive Messaging

Set `MASTER_TELEGRAM_CHAT_ID` to receive scheduled briefings from the APScheduler background job:

```env
MASTER_TELEGRAM_CHAT_ID=123456789
PROACTIVE_CHECK_INTERVAL_MINUTES=30
```

---

## Email

Uses `imap_tools` (sync, threaded) for reading and `aiosmtplib` (async) for sending.

### Setup

```env
EMAIL_IMAP_SERVER=imap.gmail.com
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_ADDRESS=your@gmail.com
EMAIL_APP_PASSWORD=your-app-password
```

For **Gmail**, generate an App Password:  
Google Account → Security → 2-Step Verification → App passwords

### Available Tools

| Tool | Direction | Confirmation? |
|---|---|---|
| `send_email` | Outbound (SMTP) | ✅ |
| `read_unread_emails` | Inbound (IMAP) | ❌ |

---

## Unified Send API

Both channels share the same outbound endpoint:

```bash
curl -X POST http://localhost:8000/api/v1/messaging/send \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "telegram",
    "to": "123456789",
    "message": "Hello from Amadeus!"
  }'
```

Supported `channel` values: `"telegram"`, `"email"` (email requires a `"subject"` field).

---

*← [[Redis-Quota-Tracking]] | [[Security-Model]] →*
