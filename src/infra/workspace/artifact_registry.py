"""
ArtifactRegistry — append-only index of everything written to AMASPACE.

Each persisted artifact appends one JSON line to ``AMASPACE/.index/artifacts.jsonl``.
This keeps the corpus traceable and lays the groundwork for future search /
vector indexing without forcing a database dependency on the lean local daemon.

The registry is intentionally tiny and dependency-free (stdlib + numpy-free).
Reads scan the file lazily; writes are atomic-append under a thread lock.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from src.core.domain.artifacts import ArtifactMetadata


logger = logging.getLogger(__name__)


class ArtifactRegistry:
    """Append-only JSONL index of persisted artifacts."""

    def __init__(self, index_dir: Path) -> None:
        self._index_dir = Path(index_dir)
        self._index_path = self._index_dir / "artifacts.jsonl"
        self._lock = threading.Lock()

    @property
    def index_path(self) -> Path:
        return self._index_path

    def append(self, metadata: ArtifactMetadata) -> None:
        """Append a single artifact record to the index (best-effort)."""
        line = json.dumps(metadata.to_dict(), ensure_ascii=False)
        try:
            with self._lock:
                self._index_dir.mkdir(parents=True, exist_ok=True)
                with self._index_path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except OSError as exc:
            # Indexing must never break artifact persistence — log and move on.
            logger.warning("artifact_index_append_failed: %s", exc)

    def all(self) -> list[ArtifactMetadata]:
        """Return every indexed artifact (skips corrupt lines)."""
        if not self._index_path.exists():
            return []
        records: list[ArtifactMetadata] = []
        with self._index_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    records.append(ArtifactMetadata.from_dict(json.loads(raw)))
                except (json.JSONDecodeError, KeyError, ValueError) as exc:
                    logger.debug("artifact_index_skip_corrupt_line: %s", exc)
        return records

    def search(self, query: str, *, limit: int = 20) -> list[ArtifactMetadata]:
        """Naive substring search over title / origin / tags.

        A deliberate placeholder for the future vector/semantic index — the
        interface stays stable while the implementation can be upgraded.
        """
        q = query.strip().lower()
        if not q:
            return []
        hits: list[ArtifactMetadata] = []
        for record in self.all():
            haystack = " ".join(
                [record.title, record.origin, " ".join(record.tags)]
            ).lower()
            if q in haystack:
                hits.append(record)
                if len(hits) >= limit:
                    break
        return hits
