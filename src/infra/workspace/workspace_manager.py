"""
WorkspaceManager — owns the AMASPACE directory layout and safe path resolution.

Responsibilities:
  * Create and maintain the canonical AMASPACE sub-directory tree.
  * Turn an (artifact_type, filename, subdir) request into a concrete,
    collision-safe path that is guaranteed to live *inside* AMASPACE.
  * Slugify human titles into filesystem-safe names.

It deliberately knows nothing about artifact metadata or indexing — that is
the job of :class:`ArtifactRegistry` / :class:`StorageService`.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from src.core.domain.artifacts import ArtifactType


logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
# Characters allowed verbatim in an explicitly-provided filename. Anything else
# (path separators, spaces, shell metacharacters) is replaced with '-'.
_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_SLUG_LEN = 60


def slugify(text: str, *, default: str = "untitled") -> str:
    """Convert arbitrary text into a lowercase, filesystem-safe slug."""
    slug = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    slug = slug[:_MAX_SLUG_LEN].strip("-")
    return slug or default


def sanitize_filename(name: str, *, default: str = "artifact") -> str:
    """Sanitise an explicit filename, preserving its stem/extension shape.

    Unlike :func:`slugify`, this keeps underscores, dots, and case so a caller
    asking for ``research_manifest.json`` gets exactly that — only unsafe
    characters (path separators, spaces) are normalised away.
    """
    cleaned = _FILENAME_SAFE_RE.sub("-", name.strip()).strip("-._")
    return cleaned or default


class WorkspaceContainmentError(RuntimeError):
    """Raised when a resolved path would escape the AMASPACE root."""


class WorkspaceManager:
    """Manages the on-disk AMASPACE workspace."""

    def __init__(self, root: Path, *, enforce_containment: bool = True) -> None:
        self._root = Path(root).resolve()
        self._enforce_containment = enforce_containment

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def ensure_layout(self) -> None:
        """Create AMASPACE and every canonical sub-directory (idempotent)."""
        self._root.mkdir(parents=True, exist_ok=True)
        for subdir in ArtifactType.subdirs():
            (self._root / subdir).mkdir(parents=True, exist_ok=True)
        # Hidden index dir for the artifact registry.
        (self._root / ".index").mkdir(parents=True, exist_ok=True)

    def dir_for(self, artifact_type: ArtifactType, subdir: str | None = None) -> Path:
        """Return (and create) the directory for an artifact type / optional sub-folder."""
        target = self._root / artifact_type.value
        if subdir:
            target = target / sanitize_filename(subdir, default="run")
        target = self._guard(target)
        target.mkdir(parents=True, exist_ok=True)
        return target

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------
    def resolve(
        self,
        artifact_type: ArtifactType,
        *,
        filename: str | None = None,
        title: str | None = None,
        subdir: str | None = None,
        timestamp_prefix: bool = True,
        date_str: str | None = None,
        collision_safe: bool = True,
    ) -> Path:
        """Resolve a concrete, contained, collision-safe artifact path.

        Exactly one of *filename* or *title* should be provided. When only a
        title is given, the name becomes ``<YYYY-MM-DD>_<slug>`` (markdown).
        """
        directory = self.dir_for(artifact_type, subdir)

        name = self._build_name(
            filename=filename,
            title=title,
            timestamp_prefix=timestamp_prefix,
            date_str=date_str,
        )

        candidate = self._guard(directory / name)
        if collision_safe:
            candidate = self._dedupe(candidate)
        return candidate

    def relative_path(self, path: Path) -> str:
        """Return *path* relative to the AMASPACE root (POSIX style)."""
        return path.resolve().relative_to(self._root).as_posix()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _build_name(
        self,
        *,
        filename: str | None,
        title: str | None,
        timestamp_prefix: bool,
        date_str: str | None,
    ) -> str:
        if filename:
            # Preserve the caller's filename shape (stem + extension); only strip
            # unsafe characters so e.g. ``research_manifest.json`` survives intact.
            base = sanitize_filename(filename, default="artifact")
            if not Path(base).suffix:
                base = f"{base}.md"
        else:
            stem = slugify(title or "", default="untitled")
            base = f"{stem}.md"

        if timestamp_prefix and date_str:
            return f"{date_str}_{base}"
        return base

    def _dedupe(self, path: Path) -> Path:
        """Append ``-1``, ``-2`` ... to the stem until the path is free."""
        if not path.exists():
            return path
        stem, suffix, parent = path.stem, path.suffix, path.parent
        for i in range(1, 10_000):
            candidate = parent / f"{stem}-{i}{suffix}"
            if not candidate.exists():
                return candidate
        # Pathological fallback — should never be hit in practice.
        raise WorkspaceContainmentError(f"Could not find a free filename for {path}")

    def _guard(self, path: Path) -> Path:
        """Ensure *path* stays within the AMASPACE root."""
        resolved = path.resolve()
        if self._enforce_containment:
            try:
                resolved.relative_to(self._root)
            except ValueError as exc:
                raise WorkspaceContainmentError(
                    f"Refusing to write outside AMASPACE: {resolved} (root={self._root})"
                ) from exc
        return resolved
