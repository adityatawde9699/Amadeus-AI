"""
Long-Term Semantic Memory Service for Amadeus AI.

Uses Qdrant as a local, persistent vector database and Google Gemini's
embedding API to encode and retrieve memories semantically.

Architecture:
- Every user/assistant message is embedded and stored with metadata.
- On each new query, the top-K most semantically similar past messages are
  retrieved via cosine similarity and injected into the LLM prompt.
- Graceful degradation: if Qdrant or embeddings fail, the service logs
  the error and returns empty results (memory simply disabled, not crashed).

Usage:
    memory = QdrantMemoryService(settings)
    await memory.store(session_id="abc", role="user", text="I love astronomy")
    memories = await memory.retrieve(query="What do I enjoy?", top_k=5)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.core.config import Settings, get_settings


logger = logging.getLogger(__name__)


# =============================================================================
# RESULT DATACLASS
# =============================================================================


class MemoryResult:
    """A single semantic memory retrieved from the vector store."""

    __slots__ = (
        "distance",
        "role",
        "session_id",
        "text",
        "timestamp",
        "type",
        "subtype",
        "importance",
        "source",
        "score",
    )

    def __init__(
        self,
        session_id: str,
        role: str,
        text: str,
        timestamp: str,
        distance: float = 0.0,
        type: str = "memory",
        subtype: str = "interaction",
        importance: float = 0.5,
        source: str = "user",
        score: float = 0.0,
    ) -> None:
        self.session_id = session_id
        self.role = role
        self.text = text
        self.timestamp = timestamp
        self.distance = distance  # Raw cosine similarity
        self.type = type
        self.subtype = subtype
        self.importance = importance
        self.source = source
        self.score = score  # Final weighted score

    def __repr__(self) -> str:
        return f"<MemoryResult subtype={self.subtype!r} score={self.score:.3f} text={self.text[:40]!r}>"


# =============================================================================
# QDRANT MEMORY SERVICE
# =============================================================================
# FLASH MEMORY L1 CACHE
# =============================================================================


class FlashMemoryCache:
    """
    Tier-1 in-memory ring-buffer that intercepts Qdrant calls for recently
    stored memories.

    Architecture
    -----------
    - Pre-allocates a (capacity × dim) NumPy float32 matrix on first push.
    - New memories are written in a circular fashion (oldest is overwritten).
    - At query time: single matrix-vector dot product over the active rows
      returns cosine similarities in one C-array call — sub-microsecond on
      an i3 for capacity=100.
    - If best_score ≥ threshold → return the cached MemoryResult immediately,
      skipping Qdrant entirely.
    - If no hit → falls through to the normal Qdrant lookup.

    RAM cost: capacity × dim × 4 bytes = 100 × 768 × 4 ≈ 307 KB. Trivial.

    Parameters
    ----------
    capacity:
        Maximum number of memories held in the L1 cache (ring buffer).
    threshold:
        Minimum cosine similarity to accept a cache hit (default 0.85).
    """

    def __init__(self, capacity: int = 100, threshold: float = 0.85) -> None:
        self._capacity = capacity
        self._threshold = threshold
        self._embeddings: Any = None           # np.ndarray (capacity, dim), lazy-init
        self._entries: list[Any] = [None] * capacity  # parallel MemoryResult list
        self._head: int = 0                    # next write position
        self._slots: int = 0                   # number of valid entries (0 → capacity)

    def push(self, result: Any, embedding: list[float]) -> None:
        """
        Add a memory + its embedding to the ring buffer.
        Overwrites the oldest entry once the buffer is full.
        """
        import numpy as np

        emb = np.array(embedding, dtype=np.float32)
        # L2-normalise so the dot product equals cosine similarity
        norm = float(np.linalg.norm(emb))
        if norm > 0:
            emb /= norm

        # Lazy-initialise the matrix on the first push
        if self._embeddings is None:
            self._embeddings = np.zeros((self._capacity, emb.shape[0]), dtype=np.float32)

        self._embeddings[self._head] = emb
        self._entries[self._head] = result
        self._head = (self._head + 1) % self._capacity
        self._slots = min(self._slots + 1, self._capacity)

    def check(self, query_embedding: list[float]) -> Any:
        """
        Return the best-matching MemoryResult if its cosine similarity to
        query_embedding is ≥ threshold, otherwise return None.
        """
        if self._slots == 0 or self._embeddings is None:
            return None

        import numpy as np

        q = np.array(query_embedding, dtype=np.float32)
        norm = float(np.linalg.norm(q))
        if norm > 0:
            q /= norm

        # Cosine similarity across all active slots (pure NumPy → C BLAS)
        scores: Any = self._embeddings[: self._slots] @ q  # shape (slots,)
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])

        if best_score >= self._threshold:
            hit = self._entries[best_idx]
            if hit is not None:
                hit.score = best_score  # surface the actual score to caller
                return hit

        return None

    def invalidate(self) -> None:
        """Clear all cached entries (e.g. after a session reset)."""
        self._embeddings = None
        self._entries = [None] * self._capacity
        self._head = 0
        self._slots = 0

    @property
    def size(self) -> int:
        """Number of valid entries currently in the cache."""
        return self._slots


# =============================================================================
# QDRANT MEMORY SERVICE
# =============================================================================


# Global cache for the Qdrant client to avoid FileLock collisions
_global_qdrant_client = None


class QdrantMemoryService:
    """
    Long-term semantic memory powered by Qdrant + Gemini embeddings.

    Stores all conversation messages as vector embeddings for cross-session
    semantic retrieval. This enables the assistant to recall preferences,
    past discussions, and user-specific context from any prior session.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Any = None
        self._embed_model: Any = None
        # Reuse CHROMA settings for Qdrant location/collection name
        self._enabled = self._settings.CHROMA_ENABLED
        self._initialized = False

        # Tier-1 Flash Memory Cache (intercepts Qdrant for recent memories)
        self._flash_cache = FlashMemoryCache(capacity=100, threshold=0.85)

    async def initialize(self) -> None:
        """Call this async method before using the service."""
        if self._enabled:
            await self._setup()

    # -------------------------------------------------------------------------
    # Setup / Initialization
    # -------------------------------------------------------------------------

    async def _setup(self) -> None:
        """Initialize Qdrant async client and Gemini embedding model."""
        global _global_qdrant_client
        try:
            # Using the same persist path but handled by Qdrant
            from qdrant_client import AsyncQdrantClient
            from qdrant_client.models import Distance, VectorParams

            Path(str(self._settings.CHROMA_PERSIST_DIR)).mkdir(parents=True, exist_ok=True)

            if _global_qdrant_client is None:
                _global_qdrant_client = AsyncQdrantClient(path=self._settings.CHROMA_PERSIST_DIR)

            self._client = _global_qdrant_client

            # Setup embedding model first — must happen before collection creation
            # so we know the correct vector dimension (384 local vs 768 Gemini)
            self._setup_embedding_model()

            if not self._enabled:
                return

            collection_name = self._settings.CHROMA_COLLECTION_NAME
            embed_dim = getattr(self, "_embed_dim", 384)

            # Check if collection exists with correct dimensions
            if await self._client.collection_exists(collection_name=collection_name):
                # Verify dimension matches — recreate if mismatched (e.g. switched embedder)
                try:
                    info = await self._client.get_collection(collection_name)
                    existing_dim = info.config.params.vectors.size  # type: ignore[union-attr]
                    if existing_dim != embed_dim:
                        logger.warning(
                            "Qdrant collection dimension mismatch (%d vs %d). "
                            "Dropping and recreating collection.",
                            existing_dim,
                            embed_dim,
                        )
                        await self._client.delete_collection(collection_name)
                        await self._client.create_collection(
                            collection_name=collection_name,
                            vectors_config=VectorParams(size=embed_dim, distance=Distance.COSINE),
                        )
                except Exception:
                    pass  # Collection info check failed — leave it as-is
            else:
                await self._client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=embed_dim, distance=Distance.COSINE),
                )

            logger.info(
                "Qdrant memory initialized — collection=%s, dim=%d, persist_dir=%s",
                collection_name,
                embed_dim,
                self._settings.CHROMA_PERSIST_DIR,
            )
            self._initialized = True
        except Exception as exc:
            logger.exception("Qdrant setup failed — memory disabled: %s", exc)
            self._enabled = False

    def _setup_embedding_model(self) -> None:
        """
        Configure embedding model with local-first priority:
          1. sentence-transformers (local, offline, free, no quota)
          2. Gemini embedding API (cloud fallback, requires API key + quota)
        """
        # --- Try local sentence-transformers first ---
        try:
            from sentence_transformers import SentenceTransformer

            # all-MiniLM-L6-v2: ~80MB, 384-dim, fast and memory efficient
            self._local_embed_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            self._embed_dim = 384
            self._use_local_embed = True
            logger.info(
                "Local sentence-transformers embedding model loaded (all-MiniLM-L6-v2, dim=384)"
            )
            return
        except ImportError:
            logger.warning(
                "sentence-transformers not installed — will try Gemini embeddings. "
                "Install with: pip install sentence-transformers"
            )
        except Exception as exc:
            logger.warning("Local embedding model failed to load: %s — trying Gemini", exc)

        # --- Fall back to Gemini ---
        self._use_local_embed = False
        if not self._settings.GEMINI_API_KEY:
            logger.warning(
                "No local embed model and GEMINI_API_KEY not set — semantic memory disabled."
            )
            self._enabled = False
            return

        try:
            from google import genai

            self._genai_client = genai.Client(api_key=self._settings.GEMINI_API_KEY)
            self._embed_model = self._settings.MEMORY_EMBED_MODEL
            self._embed_dim = 768  # Gemini embedding dimension
            logger.info("Gemini embedding model ready (fallback): %s", self._embed_model)
        except Exception as exc:
            logger.exception("Gemini embedding setup failed — memory disabled: %s", exc)
            self._enabled = False

    # -------------------------------------------------------------------------
    # Async Embedding Helpers
    # -------------------------------------------------------------------------

    async def _embed_async(
        self, text: str, task_type: str = "retrieval_document"
    ) -> list[float] | None:
        """Embed text using local model (preferred) or Gemini (fallback)."""
        if not self._enabled:
            return None

        # Local embedding path — runs in executor to stay non-blocking
        if getattr(self, "_use_local_embed", False):
            try:
                loop = asyncio.get_running_loop()

                def _local_embed() -> list[float]:
                    vec = self._local_embed_model.encode(text, show_progress_bar=False)
                    return vec.tolist()

                return await loop.run_in_executor(None, _local_embed)
            except Exception as exc:
                logger.warning("Local embedding failed: %s", exc)
                return None

        # Gemini embedding fallback
        if not getattr(self, "_embed_model", None):
            return None

        def _sync_embed() -> list[float]:
            from google.genai import types

            result = self._genai_client.models.embed_content(
                model=self._embed_model,
                contents=text,
                config=types.EmbedContentConfig(task_type=task_type),
            )
            embeddings = result.embeddings
            if not embeddings:
                raise ValueError("No embeddings returned")
            values = embeddings[0].values
            if values is None:
                raise ValueError("No embedding values returned")
            return list(values)

        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, _sync_embed)
        except Exception as exc:
            logger.warning("Gemini embedding failed: %s", exc)
            return None

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def store(
        self,
        session_id: str,
        role: str,
        text: str,
        type: str = "memory",
        subtype: str = "interaction",
        importance: float = 0.5,
        source: str = "user",
    ) -> bool:
        """
        Embed and persist a message into the vector store with metadata.
        """
        if not self._enabled or not self._initialized:
            return False

        # Identity memories have fixed high importance
        if subtype == "identity":
            importance = 1.0

        embedding = await self._embed_async(text, "retrieval_document")
        if embedding is None:
            return False

        # Build a stable, unique document ID — Qdrant requires a valid UUID
        timestamp_str = datetime.now(UTC).isoformat()
        raw_key = f"{session_id}:{role}:{text}:{timestamp_str}"
        id_str = str(uuid.uuid5(uuid.NAMESPACE_OID, raw_key))

        try:
            from qdrant_client.models import PointStruct

            await self._client.upsert(
                collection_name=self._settings.CHROMA_COLLECTION_NAME,
                points=[
                    PointStruct(
                        id=id_str,
                        vector=embedding,
                        payload={
                            "session_id": session_id,
                            "role": role,
                            "text": text,
                            "timestamp": timestamp_str,
                            "type": type,
                            "subtype": subtype,
                            "importance": importance,
                            "source": source,
                        },
                    )
                ],
            )
            logger.debug("Memory stored — id=%s, role=%s", id_str[:8], role)

            # --- Push to L1 Flash Cache ---
            # Build a MemoryResult so the cache stores the full object
            flash_result = MemoryResult(
                session_id=session_id,
                role=role,
                text=text,
                timestamp=timestamp_str,
                distance=1.0,
                type=type,
                subtype=subtype,
                importance=importance,
                source=source,
                score=1.0,
            )
            self._flash_cache.push(flash_result, embedding)

            return True
        except Exception as exc:
            logger.warning("Qdrant upsert failed: %s", exc)
            return False

    async def retrieve(self, query: str, top_k: int = 5) -> list[MemoryResult]:
        """
        Two-tier semantic retrieval:
          Tier 1 — Flash Memory Cache (NumPy cosine similarity, ~microsecond).
                    Returns immediately if any recent memory scores ≥ 0.85.
          Tier 2 — Qdrant (async network call, full historical search).
                    Only reached on L1 cache miss.
        """
        if not self._enabled or not self._initialized:
            return []

        embedding = await self._embed_async(query, "retrieval_query")
        if embedding is None:
            return []

        # --- Tier 1: Flash Memory Cache ---
        flash_hit = self._flash_cache.check(embedding)
        if flash_hit is not None:
            logger.debug(
                "Flash cache HIT (score=%.3f) — skipping Qdrant lookup.", flash_hit.score
            )
            return [flash_hit]

        # --- Tier 2: Full Qdrant search ---
        try:
            import math

            results = await self._client.search(
                collection_name=self._settings.CHROMA_COLLECTION_NAME,
                query_vector=embedding,
                limit=top_k * 2,  # Fetch more to allow for re-ranking
                with_payload=True,
            )

            memories: list[MemoryResult] = []
            now = datetime.now(UTC)
            tau_seconds = 7 * 24 * 3600  # 7 days for recency decay

            for hit in results:
                payload = hit.payload or {}

                # --- Tiered Ranking Logic ---
                similarity = hit.score

                # Filter by similarity threshold
                if similarity < 0.65:
                    continue

                importance = payload.get("importance", 0.5)
                subtype = payload.get("subtype", "interaction")

                # Calculate recency decay
                timestamp_str = payload.get("timestamp", "")
                recency_decay = 0.0
                if timestamp_str and subtype != "identity":
                    try:
                        mem_time = datetime.fromisoformat(timestamp_str)
                        if mem_time.tzinfo is None:
                            mem_time = mem_time.replace(tzinfo=UTC)
                        time_delta = (now - mem_time).total_seconds()
                        recency_decay = math.exp(-max(0, time_delta) / tau_seconds)
                    except Exception:
                        recency_decay = 0.5
                elif subtype == "identity":
                    importance = 1.0
                    recency_decay = 1.0  # Never decays

                weighted_score = (0.6 * similarity) + (0.25 * importance) + (0.15 * recency_decay)

                memories.append(
                    MemoryResult(
                        session_id=payload.get("session_id", ""),
                        role=payload.get("role", "unknown"),
                        text=payload.get("text", ""),
                        timestamp=timestamp_str,
                        distance=similarity,
                        type=payload.get("type", "memory"),
                        subtype=subtype,
                        importance=importance,
                        source=payload.get("source", "user"),
                        score=weighted_score,
                    )
                )

            # Sort by weighted score descending and take top_k
            memories.sort(key=lambda x: x.score, reverse=True)
            memories = memories[:top_k]

            logger.debug("Qdrant: retrieved %d weighted memories (L1 miss).", len(memories))
            return memories

        except Exception as exc:
            logger.warning("Qdrant search failed (client type=%s): %s", type(self._client), exc)
            return []

    async def clear_session(self, session_id: str) -> int:
        """
        Remove all stored memories for a specific session.
        """
        if not self._enabled or not self._initialized:
            return 0

        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            # Count how many we are about to delete
            count_result = await self._client.count(
                collection_name=self._settings.CHROMA_COLLECTION_NAME,
                count_filter=Filter(
                    must=[FieldCondition(key="session_id", match=MatchValue(value=session_id))]
                ),
            )
            count = count_result.count

            if count > 0:
                await self._client.delete(
                    collection_name=self._settings.CHROMA_COLLECTION_NAME,
                    points_selector=Filter(
                        must=[FieldCondition(key="session_id", match=MatchValue(value=session_id))]
                    ),
                )
                logger.info("Cleared %d memories for session=%s", count, session_id[:8])
            # Flush flash cache so no stale entries survive a session reset
            self._flash_cache.invalidate()
            return int(count)
        except Exception as exc:
            logger.warning("Qdrant session clear failed: %s", exc)
            return 0


    @property
    def is_enabled(self) -> bool:
        """True if the memory service is active and ready."""
        return self._enabled and self._initialized

    @property
    def memory_count(self) -> int:
        """Total number of stored memories across all sessions."""
        if not self._enabled or not self._initialized:
            return 0
        # Since this is an async client now, memory_count shouldn't be a synchronous property
        # that blocks. For safety in synchronous environments, returning 0.
        return 0

    async def get_memory_count(self) -> int:
        if not self._enabled or not self._initialized:
            return 0
        try:
            count = await self._client.count(self._settings.CHROMA_COLLECTION_NAME)
            return int(count.count)
        except Exception:
            return 0

    def format_for_prompt(self, memories: list[MemoryResult], max_chars: int = 1000) -> str:
        """
        Format retrieved memories as a readable string for LLM injection.
        """
        if not memories:
            return ""

        lines: list[str] = []
        char_count = 0

        for i, mem in enumerate(memories, 1):
            line = f"{i}. {mem.text}"
            if char_count + len(line) > max_chars:
                break
            lines.append(line)
            char_count += len(line)

        return "\n".join(lines)
