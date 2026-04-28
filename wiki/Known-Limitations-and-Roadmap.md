# Known Limitations & Roadmap

---

## Current Limitations

| Limitation | Notes |
|---|---|
| No user registration endpoint | Tokens must be generated externally with `SECRET_KEY` — no `/auth/register` or `/auth/login` |
| Voice WebSocket JWT enforcement | Token is checked downstream, not on the WebSocket upgrade handshake |
| Static proactive loop session list | `session_ids` in `AutonomousObservationLoop` is hardcoded — not loaded from DB |
| Windows-only Office tools | `create_excel_spreadsheet`, `create_word_document`, `send_outlook_email` require `pywin32` and only work on Windows |
| No streaming TTS | TTS audio is returned as a single binary frame after generation completes |
| No mobile/browser SDK | SSE streaming and voice endpoints must be called with raw HTTP/WebSocket |

---

## Planned Improvements

### Authentication
- `/auth/register`, `/auth/login`, `/auth/refresh` endpoints with per-user session isolation
- WebSocket JWT enforcement on the upgrade handshake (not just downstream)

### Voice
- Streaming TTS over WebSocket (chunk-by-chunk as audio arrives from Edge TTS)

### SDK
- Mobile / browser SDK for SSE streaming and voice endpoints

### Observability
- Grafana dashboard for Prometheus cost gauges

### Platform
- Dynamic skill loading — mount new tools as sandboxed Docker containers at runtime without restarting
- Proactive loop session discovery — load `session_ids` from PostgreSQL instead of a static list

---

*← [[Observability]] | [[Changelog]] →*
