# Messaging Integrations

Amadeus supports three inbound/outbound messaging channels: **Telegram**, **WhatsApp**, and **Email**.

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
- All 60+ tools are available via natural language in the chat.

### Proactive Messaging

Set `MASTER_TELEGRAM_CHAT_ID` to receive scheduled briefings from the APScheduler background job:

```env
MASTER_TELEGRAM_CHAT_ID=123456789
PROACTIVE_CHECK_INTERVAL_MINUTES=30
```

---

## WhatsApp

Uses the **Meta WhatsApp Cloud API**.

### Setup

1. Create a **Meta Business App** and add the WhatsApp product.
2. Add to `.env`:
   ```env
   WHATSAPP_ACCESS_TOKEN=your_access_token
   WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
   WHATSAPP_VERIFY_TOKEN=your_verify_token
   ```
3. Register the webhook URL in the Meta dashboard:
   ```
   https://your-domain.com/api/v1/webhooks/whatsapp
   ```
4. Meta calls the `GET` endpoint with a hub challenge to verify — the adapter handles this automatically.

### Supported Message Types

- Text send/receive
- Interactive buttons
- Pre-approved message templates

> **Note:** WhatsApp Cloud API requires a publicly accessible URL (use Railway, a VPS, or a tunnel like `ngrok` for local testing).

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

All three channels share the same outbound endpoint:

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

Supported `channel` values: `"telegram"`, `"whatsapp"`, `"email"` (email requires `"subject"` field).

---

*← [[Redis-Quota-Tracking]] | [[Security-Model]] →*
