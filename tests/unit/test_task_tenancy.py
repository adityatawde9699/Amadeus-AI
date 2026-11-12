"""
Per-user task tenancy (audit H-4) against a real SQLite database.

SQLite foreign keys are enforced here (PRAGMA foreign_keys=ON) so the
tasks.owner_id -> users.id relationship is exercised for real.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.domain.models import Task, TaskStatus
from src.infra.persistence.database import Base


@pytest_asyncio.fixture
async def session(tmp_path):
    from src.infra.persistence import orm_models  # noqa: F401 — register tables
    from src.infra.persistence.orm_models import UserORM

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        for uid in (1, 2):
            s.add(
                UserORM(
                    id=uid,
                    username=f"u{uid}",
                    email=f"u{uid}@example.test",
                    hashed_password="x",
                )
            )
        await s.flush()
        yield s
    await engine.dispose()


def _repo(session, owner):
    from src.infra.persistence.repositories.task_repository import SQLAlchemyTaskRepository

    return SQLAlchemyTaskRepository(session, owner_id=owner)


@pytest.mark.asyncio
async def test_users_only_see_and_modify_their_own_tasks(session):
    alice, bob, admin = _repo(session, 1), _repo(session, 2), _repo(session, None)

    a_task = await alice.create(Task(content="alice's"))
    b_task = await bob.create(Task(content="bob's"))

    assert [t.content for t in await alice.get_all()] == ["alice's"]
    assert [t.content for t in await bob.get_all()] == ["bob's"]
    assert await alice.count() == 1
    assert (await alice.get_summary())["total"] == 1

    # Cross-user access behaves exactly like a missing task.
    assert await alice.get_by_id(b_task.id) is None
    assert await alice.mark_complete(b_task.id) is None
    assert await alice.delete(b_task.id) is False
    assert (await bob.get_by_id(b_task.id)).status == TaskStatus.PENDING

    # Own task operations still work.
    assert (await alice.mark_complete(a_task.id)).status == TaskStatus.COMPLETED
    assert [t.content for t in await alice.get_by_status(TaskStatus.COMPLETED)] == ["alice's"]

    # The unscoped (admin / agent) view sees everything.
    assert await admin.count() == 2


@pytest.mark.asyncio
async def test_admin_route_scope_is_unscoped_user_scope_is_owned():
    from types import SimpleNamespace

    from src.api.routes.tasks import _repo as route_repo
    from src.infra.persistence.orm_models import UserRoleDB

    admin = route_repo(None, SimpleNamespace(id=7, role=UserRoleDB.ADMIN))
    user = route_repo(None, SimpleNamespace(id=8, role=UserRoleDB.USER))
    assert admin._owner_id is None
    assert user._owner_id == 8
