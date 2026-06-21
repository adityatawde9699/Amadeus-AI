"""
AMASPACE workspace persistence subsystem.

The single source of truth for every artifact Amadeus produces. Compose the
three collaborators and you get collision-safe, traceable, indexed storage:

    WorkspaceManager  — directory layout, containment, collision-safe naming
    ArtifactRegistry  — append-only index for traceability + future search
    StorageService    — high-level ``persist(Artifact) -> ArtifactRef`` facade
"""

from __future__ import annotations

from src.infra.workspace.artifact_registry import ArtifactRegistry
from src.infra.workspace.storage_service import StorageService
from src.infra.workspace.workspace_manager import WorkspaceManager


__all__ = ["ArtifactRegistry", "StorageService", "WorkspaceManager"]
