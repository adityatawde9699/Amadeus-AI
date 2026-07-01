"""
Tests for the AMASPACE workspace subsystem (Tasks 3 & 4).

Covers:
  * directory layout creation,
  * correct artifact placement by type,
  * collision-safe naming,
  * metadata generation (front-matter + sidecar + index),
  * persistence integrity (content round-trips),
  * containment guard.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from src.core.domain.artifacts import Artifact, ArtifactType
from src.infra.workspace.artifact_registry import ArtifactRegistry
from src.infra.workspace.storage_service import StorageService
from src.infra.workspace.workspace_manager import (
    WorkspaceContainmentError,
    WorkspaceManager,
    sanitize_filename,
    slugify,
)


if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def storage(tmp_path: Path) -> StorageService:
    root = tmp_path / "AMASPACE"
    wm = WorkspaceManager(root)
    wm.ensure_layout()
    return StorageService(wm, ArtifactRegistry(root / ".index"))


class TestWorkspaceLayout:
    def test_ensure_layout_creates_all_subdirs(self, tmp_path: Path) -> None:
        wm = WorkspaceManager(tmp_path / "AMASPACE")
        wm.ensure_layout()
        for subdir in ArtifactType.subdirs():
            assert (wm.root / subdir).is_dir()
        assert (wm.root / ".index").is_dir()

    def test_required_v5_subdirs_exist(self, tmp_path: Path) -> None:
        wm = WorkspaceManager(tmp_path / "AMASPACE")
        wm.ensure_layout()
        for required in (
            "research", "documents", "code", "executions",
            "logs", "exports", "memory", "datasets", "temp",
        ):
            assert (wm.root / required).is_dir(), f"{required} missing"


class TestNamingHelpers:
    def test_slugify(self) -> None:
        assert slugify("Hello, World!") == "hello-world"
        assert slugify("") == "untitled"

    def test_sanitize_filename_preserves_shape(self) -> None:
        assert sanitize_filename("research_manifest.json") == "research_manifest.json"
        assert sanitize_filename("../../etc/passwd") == "etc-passwd"


class TestPersistence:
    def test_persist_places_artifact_in_typed_dir(self, storage: StorageService) -> None:
        ref = storage.persist(
            Artifact(
                artifact_type=ArtifactType.CODE,
                title="My Script",
                content="print('hi')\n",
                origin="unit-test",
            )
        )
        assert ref.absolute_path.exists()
        assert ref.absolute_path.parent.name == "code"
        assert ref.display_path.startswith("AMASPACE/code/")

    def test_explicit_filename_preserved(self, storage: StorageService) -> None:
        ref = storage.persist(
            Artifact(
                artifact_type=ArtifactType.RESEARCH,
                title="Manifest",
                content="{}",
                origin="unit-test",
                filename="research_manifest.json",
                content_type="application/json",
                front_matter=False,
                subdir="run-1",
            )
        )
        assert ref.absolute_path.name == "research_manifest.json"

    def test_front_matter_added_for_markdown(self, storage: StorageService) -> None:
        ref = storage.persist(
            Artifact(
                artifact_type=ArtifactType.DOCUMENT,
                title="Doc",
                content="body text",
                origin="unit-test",
                tags=("a", "b"),
            )
        )
        text = ref.absolute_path.read_text()
        assert text.startswith("---\n")
        assert "type: documents" in text
        assert "body text" in text

    def test_json_artifact_has_no_front_matter(self, storage: StorageService) -> None:
        ref = storage.persist(
            Artifact(
                artifact_type=ArtifactType.EXPORT,
                title="Data",
                content='{"k": 1}',
                origin="unit-test",
                filename="data.json",
                content_type="application/json",
                front_matter=False,
            )
        )
        assert ref.absolute_path.read_text() == '{"k": 1}'

    def test_sidecar_metadata_written(self, storage: StorageService) -> None:
        ref = storage.persist(
            Artifact(
                artifact_type=ArtifactType.LOG,
                title="Log",
                content="line",
                origin="unit-test",
                request_id="req-1",
            )
        )
        sidecar = ref.absolute_path.with_suffix(ref.absolute_path.suffix + ".meta.json")
        assert sidecar.exists()
        meta = json.loads(sidecar.read_text())
        assert meta["request_id"] == "req-1"
        assert meta["artifact_type"] == "logs"
        assert meta["size_bytes"] > 0

    def test_collision_safe_naming(self, storage: StorageService) -> None:
        a = storage.persist(Artifact(ArtifactType.CODE, "dup", "x", "t", filename="a.py"))
        b = storage.persist(Artifact(ArtifactType.CODE, "dup", "y", "t", filename="a.py"))
        assert a.absolute_path != b.absolute_path
        assert b.absolute_path.name == "a-1.py"

    def test_index_records_every_artifact(self, storage: StorageService) -> None:
        storage.persist(Artifact(ArtifactType.NOTE, "n1", "c", "t"))
        storage.persist(Artifact(ArtifactType.NOTE, "n2", "c", "t"))
        records = storage.registry.all()
        assert len(records) == 2
        assert {r.title for r in records} == {"n1", "n2"}

    def test_registry_search(self, storage: StorageService) -> None:
        storage.persist(
            Artifact(ArtifactType.RESEARCH, "Quantum computing", "c", "t", tags=("physics",))
        )
        storage.persist(Artifact(ArtifactType.RESEARCH, "Cooking pasta", "c", "t"))
        hits = storage.registry.search("quantum")
        assert len(hits) == 1
        assert hits[0].title == "Quantum computing"


class TestContainment:
    def test_guard_blocks_escape(self, tmp_path: Path) -> None:
        wm = WorkspaceManager(tmp_path / "AMASPACE", enforce_containment=True)
        wm.ensure_layout()
        with pytest.raises(WorkspaceContainmentError):
            wm._guard(tmp_path / "outside.txt")

    def test_subdir_traversal_is_neutralised(self, storage: StorageService) -> None:
        # A malicious subdir is sanitised, never escapes the type directory.
        ref = storage.persist(
            Artifact(
                ArtifactType.TEMP,
                "x",
                "c",
                "t",
                subdir="../../etc",
                filename="f.txt",
            )
        )
        assert "temp" in ref.relative_path
        assert ".." not in ref.relative_path
