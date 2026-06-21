"""
RuntimeHost — transport-agnostic application lifecycle.

Encapsulates the startup/shutdown sequence that used to be inlined in the
FastAPI ``lifespan`` so it can be shared by both the FastAPI host
(``src/transports/fastapi_transport.py``) and the Telegram-first daemon
(``src/transports/telegram_daemon.py``).

Optional subsystems — MCP servers, proactive checks, and the autonomous
observation loop — are gated behind feature flags so an idle local daemon
stays small and quiet. See ``Settings`` (``ENABLE_MCP``,
``ENABLE_PROACTIVE_LOOP``, ``ENABLE_AUTONOMOUS_LOOP``, ``RUN_MIGRATIONS_ON_START``).

This module is intentionally free of any FastAPI/HTTP imports.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.core.config import Settings, validate_settings
from src.infra.persistence.database import close_db, init_db
from src.runtime.core import AmadeusRuntime
from src.transports.telegram_transport import TelegramTransport


if TYPE_CHECKING:
    from src.app.services.autonomous_loop import AutonomousObservationLoop

logger = logging.getLogger(__name__)


class RuntimeHost:
    """Owns the shared runtime lifecycle for any transport.

    Typical usage::

        host = RuntimeHost(get_settings())
        await host.start()
        ...
        await host.stop()
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.runtime: AmadeusRuntime | None = None
        self.telegram: TelegramTransport | None = None
        self.scheduler: AsyncIOScheduler | None = None
        self.observation_loop: AutonomousObservationLoop | None = None
        self._started = False

    async def start(self) -> None:
        """Bring the runtime up: DB, runtime services, Telegram polling, loops."""
        settings = self.settings
        logger.info(
            "Starting RuntimeHost for %s v%s",
            settings.ASSISTANT_NAME,
            settings.ASSISTANT_VERSION,
        )

        # 1. Validate configuration
        validation = validate_settings()
        if validation.get("errors"):
            logger.error("Configuration errors: %s", validation["errors"])
            if settings.is_production:
                raise RuntimeError("Configuration errors in production")
        for warning in validation.get("warnings", []):
            logger.warning("Config warning: %s", warning)

        # 2. Database migrations (opt-in — migrations are an install/update step)
        if settings.RUN_MIGRATIONS_ON_START:
            await self._run_migrations()
        else:
            logger.info("RUN_MIGRATIONS_ON_START disabled — skipping Alembic at startup")

        # 3. Initialize database
        await init_db()

        # 4. Core runtime (AmadeusService, LLM router, tools, memory)
        self.runtime = AmadeusRuntime(settings)
        await self.runtime.start()

        # 5. MCP servers (opt-in — external tool-execution channel)
        if settings.ENABLE_MCP:
            await self._connect_mcp_servers()
        else:
            logger.info("ENABLE_MCP disabled — skipping MCP server connections")

        # 6. Shared HTTP sessions used by the info and finance tools
        from src.infra.tools.finance_tools import initialize_finance_tools_http_session
        from src.infra.tools.info_tools import initialize_info_tools_http_session

        await initialize_info_tools_http_session()
        await initialize_finance_tools_http_session()

        # 7. Telegram long polling (primary client). Safe no-op without a token.
        logger.info("Starting Telegram long polling...")
        self.telegram = TelegramTransport(runtime=self.runtime)
        started = await self.telegram.start_polling()
        if not started:
            logger.warning(
                "Telegram polling not started — see logs above for details. "
                "Common causes: missing TELEGRAM_BOT_TOKEN, network timeout "
                "(set TELEGRAM_CONNECT_TIMEOUT / TELEGRAM_PROXY_URL in .env), "
                "or python-telegram-bot not installed."
            )

        # 8. Proactive checks (opt-in)
        if settings.ENABLE_PROACTIVE_LOOP:
            self._start_proactive_loop()
        else:
            logger.info("ENABLE_PROACTIVE_LOOP disabled — proactive checks not scheduled")

        # 9. Autonomous observation loop (opt-in)
        if settings.ENABLE_AUTONOMOUS_LOOP:
            from src.app.services.autonomous_loop import AutonomousObservationLoop

            self.observation_loop = AutonomousObservationLoop(
                interval_minutes=60, session_ids=["system_default_session"]
            )
            await self.observation_loop.start()
        else:
            logger.info("ENABLE_AUTONOMOUS_LOOP disabled — observation loop not started")

        self._started = True
        logger.info("RuntimeHost started.")

    async def stop(self) -> None:
        """Tear everything down symmetrically. Safe to call if start() partially ran."""
        logger.info("Stopping RuntimeHost...")

        if self.scheduler is not None and self.scheduler.running:
            # wait=True lets in-flight jobs finish before the loop closes
            self.scheduler.shutdown(wait=True)

        if self.telegram is not None:
            await self.telegram.stop_polling()

        if self.observation_loop is not None:
            self.observation_loop.stop()

        from src.infra.tools.finance_tools import close_finance_tools_http_session
        from src.infra.tools.info_tools import close_info_tools_http_session

        await close_info_tools_http_session()
        await close_finance_tools_http_session()

        if self.runtime is not None:
            if self.runtime.tools is not None:
                await self.runtime.tools.shutdown_mcp()
            await self.runtime.stop()

        await close_db()
        self._started = False
        logger.info("RuntimeHost stopped.")

    # ------------------------------------------------------------------ helpers

    async def _run_migrations(self) -> None:
        """Run Alembic ``upgrade head`` as a subprocess (avoids event-loop deadlock)."""
        settings = self.settings
        try:
            logger.info("Running database migrations...")
            alembic_cfg_path = settings.BASE_DIR / "alembic.ini"
            alembic_script_location = settings.BASE_DIR / "alembic"

            if alembic_cfg_path.exists() and alembic_script_location.exists():
                # alembic/env.py calls asyncio.run() which deadlocks inside the
                # already-running loop; run it out-of-process instead.
                # Wrap in a lambda so the type-checker can resolve the return type
                # as CompletedProcess[str] rather than FunctionType (subprocess.run
                # has many overloads that confuse inference when passed as a bare
                # callable reference with forwarded *args/**kwargs).
                result = await asyncio.to_thread(
                    lambda: subprocess.run(
                        [sys.executable, "-m", "alembic", "upgrade", "head"],
                        cwd=str(settings.BASE_DIR),
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                )
                if result.returncode == 0:
                    logger.info("Database migrations complete")
                else:
                    logger.error("Alembic migration failed: %s", result.stderr)
                    if settings.is_production:
                        raise RuntimeError(f"Migration failed: {result.stderr}")
            else:
                logger.warning(
                    "Alembic config or scripts missing at %s. Skipping migrations.",
                    settings.BASE_DIR,
                )
        except Exception as e:
            logger.exception("Failed to run migrations: %s", e)
            if settings.is_production:
                raise

    async def _connect_mcp_servers(self) -> None:
        """Connect to enabled MCP servers from ``config/mcp_servers.yaml``."""
        settings = self.settings
        mcp_config_path = settings.BASE_DIR / "config" / "mcp_servers.yaml"
        if not mcp_config_path.exists():
            logger.info("No MCP config at %s — skipping", mcp_config_path)
            return
        if self.runtime is None or self.runtime.tools is None:
            return

        import yaml

        try:
            mcp_config = yaml.safe_load(mcp_config_path.read_text())
            for server in mcp_config.get("mcp_servers", []):
                if server.get("enabled"):
                    await self.runtime.tools.connect_mcp_server(server["command"], server["name"])
        except Exception:
            logger.exception("Failed to initialize MCP servers")

    def _start_proactive_loop(self) -> None:
        """Schedule the recurring proactive checks job."""
        from src.app.services.proactive_service import run_proactive_checks

        self.scheduler = AsyncIOScheduler()
        interval_minutes = self.settings.PROACTIVE_CHECK_INTERVAL_MINUTES
        self.scheduler.add_job(
            run_proactive_checks,
            "interval",
            minutes=interval_minutes,
            id="proactive_checks_job",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info("Proactive checks scheduled every %d minutes", interval_minutes)
