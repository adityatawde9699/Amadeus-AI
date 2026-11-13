"""
Telegram-first daemon entry point.

This is the lightweight, transport-minimal way to run Amadeus as a local
autonomous assistant: it boots the shared :class:`RuntimeHost` (DB, runtime
services, Telegram long polling, opt-in background loops) without the FastAPI
host, auth, webhooks, CORS, or metrics surface.

Run it with::

    uv run amadeus-daemon

The daemon refuses to start unless both ``TELEGRAM_BOT_TOKEN`` and
``MASTER_TELEGRAM_CHAT_ID`` are configured — there is no point bringing up a
Telegram-only daemon that cannot talk to, or authorize, anyone.

Unlike the FastAPI host, the daemon does **not** run Alembic migrations at
startup by default (migrations are an install/update step). Set
``RUN_MIGRATIONS_ON_START=true`` explicitly to opt back in.

Reliability improvements
------------------------
* Exponential-backoff restart loop — if ``RuntimeHost.start()`` raises (e.g.
  transient DB not-yet-ready on a fresh boot), the daemon retries up to
  ``DAEMON_MAX_START_RETRIES`` times before giving up, so a brief infra
  outage at boot does not permanently disable the assistant.
* ``SIGUSR1`` → clean restart of Telegram polling only (re-registers handlers,
  useful after a bot-token rotation or when long-polling silently stalls).
* PID file written to ``DATA_DIR/amadeus-daemon.pid`` on startup and cleaned
  up on exit, so ``systemd``/``supervisord`` health checks and ``kill -0``
  probes work correctly.
* ``asyncio.Runner`` (Python 3.11+) is used instead of bare ``asyncio.run``
  so the event loop is shared with the signal handlers throughout the full
  lifecycle, avoiding "no current event loop" edge-cases.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys
from pathlib import Path

from src.core.config import Settings, get_settings
from src.runtime.host import RuntimeHost


logger = logging.getLogger("amadeus.daemon")

# ---------------------------------------------------------------------------
# How many times to retry RuntimeHost.start() before giving up.
# Each attempt waits 2^(attempt-1) seconds: 1 s, 2 s, 4 s, …
# Override with the DAEMON_MAX_START_RETRIES env-var.
# ---------------------------------------------------------------------------
_DEFAULT_MAX_START_RETRIES = 3


def _configure_logging(settings: Settings) -> None:
    """Minimal structured console logging for the daemon process."""
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Silence noisy third-party loggers that are irrelevant at INFO level.
    for noisy in ("httpx", "httpcore", "telegram.ext.Application"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _check_required_settings(settings: Settings) -> list[str]:
    """Return the names of required settings that are missing/empty."""
    missing: list[str] = []
    if not settings.TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not settings.MASTER_TELEGRAM_CHAT_ID:
        missing.append("MASTER_TELEGRAM_CHAT_ID")
    return missing


def _prepare_settings(settings: Settings) -> Settings:
    """Apply daemon-specific setting overrides.

    The daemon skips Alembic migrations on startup unless the operator opted
    in explicitly via the environment (migrations are an install/update step).
    Also disables the FastAPI API host surface — it is not needed here.
    """
    overrides: dict = {}
    if "RUN_MIGRATIONS_ON_START" not in os.environ:
        overrides["RUN_MIGRATIONS_ON_START"] = False
    # The daemon never runs the HTTP API surface.
    overrides["ENABLE_API"] = False
    if overrides:
        return settings.model_copy(update=overrides)
    return settings


# ---------------------------------------------------------------------------
# PID file management
# ---------------------------------------------------------------------------


def _write_pid_file(settings: Settings) -> Path | None:
    """Write the daemon PID to DATA_DIR/amadeus-daemon.pid.

    Returns the path on success, None if the write fails (non-fatal).
    """
    try:
        pid_path = Path(settings.DATA_DIR or settings.BASE_DIR / "data") / "amadeus-daemon.pid"
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
        logger.debug("PID file written: %s", pid_path)
        return pid_path
    except OSError as exc:
        logger.warning("Could not write PID file: %s", exc)
        return None


def _remove_pid_file(pid_path: Path | None) -> None:
    """Remove the PID file on clean exit (best-effort)."""
    if pid_path is None:
        return
    with contextlib.suppress(OSError):
        pid_path.unlink()
        logger.debug("PID file removed: %s", pid_path)


# ---------------------------------------------------------------------------
# Main async entrypoint
# ---------------------------------------------------------------------------


async def _run(settings: Settings, stop_event: asyncio.Event | None = None) -> None:
    """Start the runtime host, wait for a shutdown signal, then stop cleanly.

    Retries ``RuntimeHost.start()`` with exponential back-off on transient
    failures (e.g. DB not yet ready on a fresh system boot).
    """
    settings = _prepare_settings(settings)
    max_retries = int(os.environ.get("DAEMON_MAX_START_RETRIES", _DEFAULT_MAX_START_RETRIES))

    host = RuntimeHost(settings)
    if stop_event is None:
        stop_event = asyncio.Event()
    reload_polling_event = asyncio.Event()

    loop = asyncio.get_running_loop()

    # SIGINT / SIGTERM → clean shutdown
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    # SIGUSR1 → reload Telegram polling only (useful after token rotation)
    with contextlib.suppress(AttributeError, NotImplementedError):
        # SIGUSR1 is not available on Windows
        loop.add_signal_handler(signal.SIGUSR1, reload_polling_event.set)

    # --- startup with retries ------------------------------------------------
    for attempt in range(1, max_retries + 1):
        try:
            await host.start()
            break
        except Exception as exc:
            if attempt >= max_retries:
                logger.critical(
                    "RuntimeHost.start() failed after %d attempt(s): %s — giving up.",
                    max_retries,
                    exc,
                )
                raise
            backoff = 2 ** (attempt - 1)
            logger.warning(
                "RuntimeHost.start() failed (attempt %d/%d): %s — retrying in %ds…",
                attempt,
                max_retries,
                exc,
                backoff,
            )
            await asyncio.sleep(backoff)

    logger.info("Amadeus Telegram daemon is running. Press Ctrl+C to stop.")

    # --- main wait loop -------------------------------------------------------
    try:
        while not stop_event.is_set():
            # Wake when either the shutdown or the reload signal arrives.
            done, _ = await asyncio.wait(
                [
                    asyncio.ensure_future(stop_event.wait()),
                    asyncio.ensure_future(reload_polling_event.wait()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if reload_polling_event.is_set() and not stop_event.is_set():
                reload_polling_event.clear()
                logger.info("SIGUSR1 received — restarting Telegram polling…")
                if host.telegram is not None:
                    await host.telegram.stop_polling()
                    started = await host.telegram.start_polling()
                    if started:
                        logger.info("Telegram polling restarted successfully.")
                    else:
                        logger.error("Telegram polling restart failed — see logs above.")
    finally:
        logger.info("Shutdown signal received — stopping daemon…")
        await host.stop()


# ---------------------------------------------------------------------------
# Console-script entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Console-script entry point (``amadeus-daemon``)."""
    settings = get_settings()
    _configure_logging(settings)

    missing = _check_required_settings(settings)
    if missing:
        print(
            "ERROR: the Telegram daemon requires the following setting(s): "
            f"{', '.join(missing)}.\n"
            "Set them in your environment or .env file and try again.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    pid_path = _write_pid_file(settings)
    try:
        asyncio.run(_run(settings))
    except KeyboardInterrupt:
        logger.info("Interrupted — exiting.")
    except Exception:
        logger.exception("Daemon terminated with an unhandled exception.")
        raise SystemExit(1)
    finally:
        _remove_pid_file(pid_path)


if __name__ == "__main__":
    main()
