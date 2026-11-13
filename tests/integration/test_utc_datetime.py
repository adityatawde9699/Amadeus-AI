"""Timezone-aware datetimes must be storable in the naive-UTC timestamp columns.

On PostgreSQL + asyncpg an aware value bound to ``TIMESTAMP WITHOUT TIME ZONE``
raised "can't subtract offset-naive and offset-aware datetimes", so creating a
reminder or advancing a Pomodoro crashed. Runs against the CI Postgres service
when AMADEUS_TEST_DATABASE_URL is set, otherwise a throwaway SQLite file.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.infra.persistence.database import Base, UTCDateTime


def test_bind_converts_aware_to_naive_utc():
    ist = timezone(timedelta(hours=5, minutes=30))
    bound = UTCDateTime().process_bind_param(datetime(2026, 1, 1, 10, 0, tzinfo=ist), None)
    expected = datetime(2026, 1, 1, 4, 30)  # noqa: DTZ001 (naive UTC is the stored form)
    assert bound == expected and bound.tzinfo is None
    naive = datetime(2026, 1, 1, 4, 30)  # noqa: DTZ001
    assert UTCDateTime().process_bind_param(naive, None) is naive
    assert UTCDateTime().process_bind_param(None, None) is None


@pytest.fixture
async def session(tmp_path):
    import src.infra.persistence.orm_models  # noqa: F401  (registers tables on Base)

    url = os.environ.get("AMADEUS_TEST_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        url = f"sqlite+aiosqlite:///{tmp_path}/utc.db"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
        await s.rollback()  # leave the shared CI database untouched
    await engine.dispose()


@pytest.mark.asyncio
async def test_reminder_and_pomodoro_accept_aware_datetimes(session):
    from src.core.domain.models import PomodoroSession, PomodoroState, Reminder
    from src.infra.persistence.repositories.pomodoro_repository import (
        SQLAlchemyPomodoroRepository,
    )
    from src.infra.persistence.repositories.reminder_repository import (
        SQLAlchemyReminderRepository,
    )

    reminders = SQLAlchemyReminderRepository(session)
    when = datetime.now(UTC) - timedelta(minutes=1)
    reminder = await reminders.create(Reminder(title="probe", time=when))
    assert reminder.id in [r.id for r in await reminders.get_due()]
    stored = await reminders.get_by_id(reminder.id)
    assert stored.time.replace(tzinfo=None) == when.replace(tzinfo=None)  # same UTC instant

    pomodoro = SQLAlchemyPomodoroRepository(session)
    p = await pomodoro.create(PomodoroSession(task_description="probe"))
    await pomodoro.update_state(p.id, PomodoroState.WORKING)
    await pomodoro.update_state(p.id, PomodoroState.COMPLETED, cycles_completed=1)
    assert await pomodoro.count_completed_today() >= 1
