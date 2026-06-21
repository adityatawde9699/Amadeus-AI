"""
Artifact domain models for the AMASPACE workspace.

These are pure domain objects — no filesystem or I/O concerns live here.
The :mod:`src.infra.workspace` layer is responsible for turning an
:class:`Artifact` into bytes on disk and an index entry.

An *artifact* is any concrete work product Amadeus produces (a research
report, a generated code file, an export, an execution log, a dataset...).
Every artifact carries enough metadata to be traceable back to the request
that created it and the tool/subsystem that produced it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class ArtifactType(StrEnum):
    """Canonical artifact categories.

    The string *value* doubles as the AMASPACE sub-directory name, so the
    set here is the authoritative list of top-level AMASPACE folders.
    """

    RESEARCH = "research"
    DOCUMENT = "documents"
    CODE = "code"
    EXECUTION = "executions"
    LOG = "logs"
    EXPORT = "exports"
    MEMORY = "memory"
    DATASET = "datasets"
    TEMP = "temp"

    # Legacy folders retained from the original AMASPACE layout so older
    # references keep resolving to a real directory.
    SUMMARY = "summaries"
    NOTE = "notes"
    CONVERSATION = "conversations"
    TASK = "tasks"

    @classmethod
    def subdirs(cls) -> tuple[str, ...]:
        """Return every AMASPACE sub-directory name, de-duplicated & ordered."""
        seen: dict[str, None] = {}
        for member in cls:
            seen.setdefault(member.value, None)
        return tuple(seen.keys())


@dataclass(frozen=True)
class ArtifactMetadata:
    """Traceability metadata persisted alongside every artifact.

    Written both as a sidecar ``<file>.meta.json`` and appended to the
    central artifact index so the corpus stays searchable.
    """

    artifact_id: str
    artifact_type: ArtifactType
    title: str
    created_at: datetime
    origin: str
    relative_path: str
    request_id: str | None = None
    session_id: str | None = None
    content_type: str = "text/plain"
    size_bytes: int = 0
    tags: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable representation (used for sidecar + index)."""
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type.value,
            "title": self.title,
            "created_at": self.created_at.isoformat(),
            "origin": self.origin,
            "relative_path": self.relative_path,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "tags": list(self.tags),
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtifactMetadata:
        return cls(
            artifact_id=data["artifact_id"],
            artifact_type=ArtifactType(data["artifact_type"]),
            title=data["title"],
            created_at=datetime.fromisoformat(data["created_at"]),
            origin=data["origin"],
            relative_path=data["relative_path"],
            request_id=data.get("request_id"),
            session_id=data.get("session_id"),
            content_type=data.get("content_type", "text/plain"),
            size_bytes=data.get("size_bytes", 0),
            tags=tuple(data.get("tags", ())),
            extra=data.get("extra", {}),
        )


@dataclass
class Artifact:
    """A work product to be persisted into AMASPACE.

    Construct one of these and hand it to ``StorageService.persist`` — the
    storage layer fills in collision-safe naming, front-matter, sidecar
    metadata, and the index entry.
    """

    artifact_type: ArtifactType
    title: str
    content: str
    origin: str
    # Desired filename (without directory). If omitted, derived from *title*.
    filename: str | None = None
    # Optional sub-folder under the type directory, e.g. a research run slug.
    subdir: str | None = None
    content_type: str = "text/markdown"
    request_id: str | None = None
    session_id: str | None = None
    tags: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)
    # Whether to prepend a YAML front-matter block (markdown/text only).
    front_matter: bool = True
    artifact_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ArtifactRef:
    """A pointer to a persisted artifact — safe to surface to the user.

    Carries no content, only identity + location, so it can be embedded in
    notifications without leaking the artifact body.
    """

    artifact_id: str
    artifact_type: ArtifactType
    title: str
    absolute_path: Path
    relative_path: str
    size_bytes: int

    @property
    def display_path(self) -> str:
        """Human-facing path, e.g. ``AMASPACE/research/.../report.md``."""
        return f"AMASPACE/{self.relative_path}"
