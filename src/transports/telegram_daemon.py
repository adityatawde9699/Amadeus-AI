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
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys

from src.core.config import Settings, get_settings
from src.runtime.host import RuntimeHost


logger = logging.getLogger("amadeus.daemon")


def _configure_logging(settings: Settings) -> None:
    """Minimal console logging for the daemon process."""
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


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
    """
    if "RUN_MIGRATIONS_ON_START" not in os.environ:
        return settings.model_copy(update={"RUN_MIGRATIONS_ON_START": False})
    return settings


async def _run(settings: Settings) -> None:
    """Start the runtime host, wait for a shutdown signal, then stop cleanly."""
    settings = _prepare_settings(settings)

    host = RuntimeHost(settings)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # add_signal_handler is unavailable on some platforms (e.g. Windows);
        # KeyboardInterrupt handling in main() covers SIGINT there.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    await host.start()
    logger.info("Amadeus Telegram daemon is running. Press Ctrl+C to stop.")
    try:
        await stop_event.wait()
    finally:
        logger.info("Shutdown signal received — stopping daemon...")
        await host.stop()


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

    try:
        asyncio.run(_run(settings))
    except KeyboardInterrupt:
        logger.info("Interrupted — exiting.")


if __name__ == "__main__":
    main()
