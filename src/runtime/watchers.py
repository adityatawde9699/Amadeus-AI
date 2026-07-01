"""
Event-driven autonomy — watchers + dispatcher (Phase 3).

Replaces fixed-interval polling as the *only* source of initiative. Watchers
observe the environment and ``emit`` events onto the runtime :class:`EventBus`;
an :class:`EventDispatcher` maps each event to a system-origin agent invocation
so Amadeus reacts to real triggers (a health threshold breach, a file change)
rather than waking on a timer regardless of state.

Design choices for the 4GB floor:
  * No new heavy dependencies. The file watcher uses an mtime poll (not
    ``watchdog``) so the Lite tier stays dependency-free; a future Standard/Power
    tier can swap in ``watchdog`` behind the same interface.
  * Tier-gated: Lite runs threshold checks only; Standard/Power add the file
    watcher. Each watcher is also individually flag-disablable.
  * Edge-triggered + rate-limited: a watcher emits only on a *transition* into
    an alert state, and the dispatcher caps wake-ups per hour, so an unhealthy
    host or a busy directory cannot spam the agent.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from src.core.config import Settings
    from src.runtime.events import EventBus

logger = logging.getLogger(__name__)


# Event names emitted onto the EventBus.
EVENT_THRESHOLD = "system.threshold_exceeded"
EVENT_FILE_CHANGED = "file.changed"


class Watcher(ABC):
    """Base class: owns a background task that runs :meth:`_tick` on a cadence."""

    name = "watcher"

    def __init__(self, event_bus: EventBus, interval_seconds: float) -> None:
        self._bus = event_bus
        self._interval = max(1.0, float(interval_seconds))
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopped.clear()
        await self._on_start()
        self._task = asyncio.create_task(self._loop())
        logger.info("Watcher '%s' started (interval=%.0fs)", self.name, self._interval)

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("Watcher '%s' stopped", self.name)

    async def _loop(self) -> None:
        while not self._stopped.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Watcher '%s' tick failed", self.name)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopped.wait(), timeout=self._interval)

    async def _on_start(self) -> None:
        """Optional one-time setup (e.g. establish a baseline)."""

    @abstractmethod
    async def _tick(self) -> None:
        """One observation pass; emit events as warranted."""


class ThresholdWatcher(Watcher):
    """Emits ``system.threshold_exceeded`` when host health crosses critical lines.

    Edge-triggered: re-emits only when the set of active alerts changes, so a
    sustained problem produces one wake-up, not one per tick.
    """

    name = "threshold"

    def __init__(self, event_bus: EventBus, settings: Settings) -> None:
        super().__init__(event_bus, settings.WATCHER_THRESHOLD_INTERVAL_SECONDS)
        self._settings = settings
        self._last_alerts: frozenset[str] = frozenset()

    async def _tick(self) -> None:
        alerts = await asyncio.to_thread(self._collect_alerts)
        current = frozenset(alerts)
        if current and current != self._last_alerts:
            await self._bus.emit(EVENT_THRESHOLD, {"alerts": list(alerts)})
        self._last_alerts = current

    def _collect_alerts(self) -> list[str]:
        import platform

        import psutil

        th = self._settings.get_system_thresholds()
        alerts: list[str] = []
        try:
            cpu = psutil.cpu_percent(interval=0.3)
            if cpu >= th["cpu"]["critical"]:
                alerts.append(f"CPU at {cpu:.0f}% (critical)")
            mem = psutil.virtual_memory()
            if mem.percent >= th["memory"]["critical"]:
                alerts.append(f"Memory at {mem.percent:.0f}% (critical)")
            disk_path = "C:/" if platform.system() == "Windows" else "/"
            disk = psutil.disk_usage(disk_path)
            if disk.percent >= th["disk"]["critical"]:
                alerts.append(f"Disk at {disk.percent:.0f}% (critical)")
            battery = psutil.sensors_battery()
            if (
                battery is not None
                and battery.percent <= th["battery"]["critical"]
                and not battery.power_plugged
            ):
                alerts.append(f"Battery at {battery.percent:.0f}% (critical, unplugged)")
        except Exception:
            logger.exception("ThresholdWatcher failed to read system health")
        return alerts


class FileWatcher(Watcher):
    """Emits ``file.changed`` when files appear or change in watched directories.

    Polls mtimes (no ``watchdog`` dependency). The first scan establishes a
    baseline silently so a fresh start does not flood the agent with events for
    pre-existing files.
    """

    name = "file"

    def __init__(self, event_bus: EventBus, dirs: list[str], interval_seconds: float) -> None:
        super().__init__(event_bus, interval_seconds)
        self._dirs = [Path(d).expanduser() for d in dirs]
        self._seen: dict[str, float] = {}
        self._primed = False

    async def _on_start(self) -> None:
        # Baseline scan: record current state without emitting.
        await asyncio.to_thread(self._scan, True)
        self._primed = True

    async def _tick(self) -> None:
        changes = await asyncio.to_thread(self._scan, False)
        for path, kind in changes:
            await self._bus.emit(EVENT_FILE_CHANGED, {"path": path, "change": kind})

    def _scan(self, baseline: bool) -> list[tuple[str, str]]:
        changes: list[tuple[str, str]] = []
        current: dict[str, float] = {}
        for root in self._dirs:
            if not root.exists():
                continue
            try:
                for p in root.rglob("*"):
                    if p.is_dir() or any(part.startswith(".") for part in p.parts):
                        continue
                    try:
                        mtime = p.stat().st_mtime
                    except OSError:
                        continue
                    key = str(p)
                    current[key] = mtime
                    if baseline:
                        continue
                    prev = self._seen.get(key)
                    if prev is None:
                        changes.append((key, "created"))
                    elif mtime > prev:
                        changes.append((key, "modified"))
            except Exception:
                logger.exception("FileWatcher scan failed for %s", root)
        self._seen = current
        return changes


class EventDispatcher:
    """Maps EventBus events to system-origin agent invocations, rate-limited."""

    def __init__(self, settings: Settings, amadeus_service: Any) -> None:
        self._settings = settings
        self._service = amadeus_service
        self._recent: list[float] = []

    def register(self, event_bus: EventBus) -> None:
        event_bus.on(EVENT_THRESHOLD, self._on_threshold)
        event_bus.on(EVENT_FILE_CHANGED, self._on_file_changed)

    # ---- handlers -----------------------------------------------------

    async def _on_threshold(self, payload: dict[str, Any]) -> None:
        alerts = payload.get("alerts") or []
        if not alerts:
            return
        prompt = (
            "SYSTEM EVENT — host health crossed a critical threshold: "
            + "; ".join(str(a) for a in alerts)
            + ". Decide whether the user should be proactively notified. If it is "
            "actionable, send a concise alert via an outbound message tool; "
            "otherwise finish silently."
        )
        await self._dispatch(prompt)

    async def _on_file_changed(self, payload: dict[str, Any]) -> None:
        path = payload.get("path", "")
        kind = payload.get("change", "changed")
        if not path:
            return
        prompt = (
            f"SYSTEM EVENT — a watched file was {kind}: {path}. Decide whether any "
            "action is warranted (e.g. summarising, indexing, or notifying the "
            "user). If nothing is needed, finish silently."
        )
        await self._dispatch(prompt)

    # ---- internals ----------------------------------------------------

    def _rate_limited(self) -> bool:
        now = time.monotonic()
        cutoff = now - 3600
        self._recent = [t for t in self._recent if t > cutoff]
        if len(self._recent) >= self._settings.WATCHER_MAX_EVENTS_PER_HOUR:
            return True
        self._recent.append(now)
        return False

    async def _dispatch(self, prompt: str) -> None:
        if self._rate_limited():
            logger.info("Event dispatch suppressed (rate limit reached)")
            return
        try:
            import uuid

            from src.core.domain.context import RequestContext
            from src.core.domain.models import PermissionProfile

            # Least privilege: watcher-triggered events run at STANDARD.
            ctx = RequestContext(
                request_id=str(uuid.uuid4()),
                session_id=self._settings.WATCHER_EVENT_SESSION_ID,
                user_id="system",
                permissions=PermissionProfile.STANDARD,
            )
            await self._service.handle_background_event(prompt, ctx)
        except Exception:
            logger.exception("Event dispatch failed")


async def start_watchers(
    settings: Settings, event_bus: EventBus, amadeus_service: Any
) -> list[Watcher]:
    """Build, register, and start the tier-appropriate watchers.

    Returns the started watchers (so the runtime can stop them). A no-op empty
    list when ``ENABLE_EVENT_WATCHERS`` is off.
    """
    if not settings.ENABLE_EVENT_WATCHERS:
        logger.info("ENABLE_EVENT_WATCHERS disabled — no watchers started")
        return []

    dispatcher = EventDispatcher(settings, amadeus_service)
    dispatcher.register(event_bus)

    tier = settings.capability.tier.value
    watchers: list[Watcher] = []

    if settings.ENABLE_THRESHOLD_WATCHER:
        watchers.append(ThresholdWatcher(event_bus, settings))

    # File watching is a Standard+ feature (mtime rglob can be heavy) and needs
    # at least one configured directory.
    if (
        settings.ENABLE_FILE_WATCHER
        and tier != "lite"
        and settings.WATCH_DIRS
    ):
        watchers.append(
            FileWatcher(event_bus, settings.WATCH_DIRS, settings.WATCHER_FILE_INTERVAL_SECONDS)
        )
    elif settings.ENABLE_FILE_WATCHER and tier == "lite":
        logger.info("File watcher skipped on Lite tier (thresholds only)")

    for w in watchers:
        await w.start()
    logger.info(
        "Event watchers started: %s (tier=%s)",
        [w.name for w in watchers] or "none", tier,
    )
    return watchers
