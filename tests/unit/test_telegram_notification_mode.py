"""
Tests for Telegram conversation-only / command-and-control mode (Task 1 & 5).

Regression protection that ensures:
  * large outputs are NOT sent to Telegram (persisted instead),
  * only short status notifications / conversational replies pass through,
  * the research command emits started → completed notifications with paths,
  * errors are reported without exposing internal traces.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.app.services.command_router import CommandRouter
from src.app.services.notification_policy import OutputDeliveryPolicy
from src.core.config import Settings
from src.core.domain.artifacts import ArtifactRef, ArtifactType
from src.core.domain.notifications import NotificationKind, TaskNotification
from src.infra.workspace.artifact_registry import ArtifactRegistry
from src.infra.workspace.storage_service import StorageService
from src.infra.workspace.workspace_manager import WorkspaceManager
from src.research.models import ResearchManifest, ResearchReport, ResearchResult


# ---------------------------------------------------------------------------
# Notification rendering
# ---------------------------------------------------------------------------


class TestNotificationRendering:
    def test_completed_with_artifact_shows_path(self) -> None:
        ref = ArtifactRef(
            artifact_id="x",
            artifact_type=ArtifactType.RESEARCH,
            title="t",
            absolute_path=Path("/tmp/AMASPACE/research/run/report.md"),
            relative_path="research/run/report.md",
            size_bytes=10,
        )
        text = TaskNotification.completed("Research", artifacts=(ref,)).render()
        assert "completed" in text
        assert "AMASPACE/research/run/report.md" in text

    def test_failed_render_carries_error_only(self) -> None:
        text = TaskNotification.failed("Research", "Research failed: TimeoutError.").render()
        assert "failed" in text
        assert "TimeoutError" in text


# ---------------------------------------------------------------------------
# OutputDeliveryPolicy
# ---------------------------------------------------------------------------


@pytest.fixture
def storage(tmp_path: Path) -> StorageService:
    root = tmp_path / "AMASPACE"
    wm = WorkspaceManager(root)
    wm.ensure_layout()
    return StorageService(wm, ArtifactRegistry(root / ".index"))


def _settings(**overrides: object) -> Settings:
    base = {"SKIP_CONFIG_VALIDATION": True, "TELEGRAM_MAX_REPLY_CHARS": 100}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestOutputDeliveryPolicy:
    def test_short_reply_passes_through(self, storage: StorageService) -> None:
        policy = OutputDeliveryPolicy(storage, _settings())
        out = policy.deliver("hello there", request_id="r", session_id="s")
        assert out == "hello there"

    def test_large_reply_is_persisted_not_sent(self, storage: StorageService) -> None:
        policy = OutputDeliveryPolicy(storage, _settings())
        big = "This is a very long generated report. " * 50  # > 100 chars
        out = policy.deliver(big, request_id="r", session_id="s")

        # The big body must NOT be in the delivered message.
        assert big not in out
        assert "AMASPACE/exports/" in out
        # And it must actually be on disk.
        records = storage.registry.all()
        assert len(records) == 1
        saved = (storage.workspace.root / records[0].relative_path).read_text()
        assert "very long generated report" in saved

    def test_disabled_mode_sends_raw(self, storage: StorageService) -> None:
        policy = OutputDeliveryPolicy(storage, _settings(TELEGRAM_NOTIFICATION_ONLY=False))
        big = "x" * 500
        assert policy.deliver(big, request_id="r", session_id="s") == big


# ---------------------------------------------------------------------------
# CommandRouter
# ---------------------------------------------------------------------------


class _FakeOrchestrator:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.called_with: str | None = None

    async def run(self, topic: str, *, request_id=None, session_id=None, progress=None):
        self.called_with = topic
        if progress:
            await progress("working")
        if self.fail:
            raise RuntimeError("boom: secret internal detail")
        ref = ArtifactRef(
            artifact_id="x",
            artifact_type=ArtifactType.RESEARCH,
            title="t",
            absolute_path=Path("/tmp/AMASPACE/research/run/report.md"),
            relative_path="research/run/report.md",
            size_bytes=10,
        )
        report = ResearchReport(topic=topic)
        manifest = ResearchManifest(
            topic=topic, slug="run", created_at=report.generated_at,
            subtopic_count=1, question_count=2, source_count=3,
            providers=["web"], stage_durations_ms={},
        )
        return ResearchResult(report=report, manifest=manifest, artifacts=[ref])


class TestCommandRouter:
    def test_parse_recognises_research(self) -> None:
        router = CommandRouter(None)
        assert router.parse("research black holes").argument == "black holes"
        assert router.parse("/research AI safety").name == "research"
        assert router.parse("hello there") is None
        assert router.parse("research") is None  # no topic

    async def test_non_command_not_handled(self) -> None:
        router = CommandRouter(_FakeOrchestrator())
        sent: list[str] = []

        async def notify(n: TaskNotification) -> None:
            sent.append(n.render())

        handled = await router.try_handle("hi there", notify=notify)
        assert handled is False
        assert sent == []

    async def test_research_emits_started_then_completed(self) -> None:
        orch = _FakeOrchestrator()
        router = CommandRouter(orch)
        sent: list[TaskNotification] = []

        async def notify(n: TaskNotification) -> None:
            sent.append(n)

        handled = await router.try_handle(
            "research exoplanets", notify=notify, request_id="r", session_id="s"
        )
        assert handled is True
        assert orch.called_with == "exoplanets"
        assert [n.kind for n in sent] == [NotificationKind.STARTED, NotificationKind.COMPLETED]
        # Completion carries the artifact path, not the report body.
        completed = sent[-1].render()
        assert "AMASPACE/research/run/report.md" in completed

    async def test_research_failure_is_sanitised(self) -> None:
        router = CommandRouter(_FakeOrchestrator(fail=True))
        sent: list[TaskNotification] = []

        async def notify(n: TaskNotification) -> None:
            sent.append(n)

        handled = await router.try_handle("research x", notify=notify)
        assert handled is True
        assert sent[-1].kind is NotificationKind.FAILED
        rendered = sent[-1].render()
        # The raw exception message must NOT leak to the user.
        assert "secret internal detail" not in rendered
        assert "RuntimeError" in rendered
