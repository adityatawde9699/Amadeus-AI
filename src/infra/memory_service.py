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

    __slots__ = ("distance", "role", "session_id", "text", "timestamp")

    def __init__(
        self,
        session_id: str,
        role: str,
        text: str,
        timestamp: str,
        distance: float = 0.0,
    ) -> None:
        self.session_id = session_id
        self.role = role
        self.text = text
        self.timestamp = timestamp
        self.distance = distance

    def __repr__(self) -> str:
        return f"<MemoryResult role={self.role!r} distance={self.distance:.3f} text={self.text[:40]!r}>"


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

            # all-MiniLM-L6-v2: 384-dim, ~80MB, fast on CPU, no GPU required
            self._local_embed_model = SentenceTransformer("all-MiniLM-L6-v2")
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
            assert embeddings is not None and len(embeddings) > 0
            values = embeddings[0].values
            assert values is not None
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

    async def store(self, session_id: str, role: str, text: str) -> bool:
        """
        Embed and persist a message into the vector store.
        """
        if not self._enabled or not self._initialized:
            return False

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
                        },
                    )
                ],
            )
            logger.debug("Memory stored — id=%s, role=%s", id_str[:8], role)
            return True
        except Exception as exc:
            logger.warning("Qdrant upsert failed: %s", exc)
            return False

    async def retrieve(self, query: str, top_k: int = 5) -> list[MemoryResult]:
        """
        Semantically retrieve the most relevant past messages for a query.
        """
        if not self._enabled or not self._initialized:
            return []

        embedding = await self._embed_async(query, "retrieval_query")
        if embedding is None:
            return []

        try:
            results = await self._client.search(
                collection_name=self._settings.CHROMA_COLLECTION_NAME,
                query_vector=embedding,
                limit=top_k,
                with_payload=True,
            )

            memories: list[MemoryResult] = []
            for hit in results:
                payload = hit.payload or {}
                memories.append(
                    MemoryResult(
                        session_id=payload.get("session_id", ""),
                        role=payload.get("role", "unknown"),
                        text=payload.get("text", ""),
                        timestamp=payload.get("timestamp", ""),
                        distance=hit.score,  # Qdrant returns similarity score
                    )
                )

            logger.debug("Retrieved %d memories for query snippet=%r", len(memories), query[:40])
            return memories

        except Exception as exc:
            logger.warning("Qdrant search failed: %s", exc)
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

        lines: list[str] = ["Relevant long-term memory (past conversations):"]
        char_count = len(lines[0])

        for mem in memories:
            prefix = "User" if mem.role == "user" else "Amadeus"
            line = f"  [{prefix}]: {mem.text}"
            if char_count + len(line) > max_chars:
                break
            lines.append(line)
            char_count += len(line)

        return "\n".join(lines)
