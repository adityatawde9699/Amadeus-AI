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
import hashlib
import logging
from datetime import UTC, datetime
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
        try:
            # Using the same persist path but handled by Qdrant
            import os

            from qdrant_client import AsyncQdrantClient
            from qdrant_client.models import Distance, VectorParams
            os.makedirs(self._settings.CHROMA_PERSIST_DIR, exist_ok=True)

            self._client = AsyncQdrantClient(path=self._settings.CHROMA_PERSIST_DIR)

            # Setup embedding model first to get expected dimension
            self._setup_embedding_model()

            if not self._enabled:
                return

            collection_name = self._settings.CHROMA_COLLECTION_NAME

            # Check if collection exists
            if not await self._client.collection_exists(collection_name=collection_name):
                # We need to know the dimension. Gemini embeddings are typically 768.
                await self._client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=768, distance=Distance.COSINE),
                )

            logger.info(
                "Qdrant memory initialized — collection=%s, persist_dir=%s",
                collection_name,
                self._settings.CHROMA_PERSIST_DIR,
            )
            self._initialized = True
        except Exception as exc:
            logger.exception("Qdrant setup failed — memory disabled: %s", exc)
            self._enabled = False

    def _setup_embedding_model(self) -> None:
        """Configure Gemini embedding model, or fall back to disabled."""
        if not self._settings.GEMINI_API_KEY:
            logger.warning(
                "GEMINI_API_KEY not set — semantic memory embedding disabled. "
                "Messages will not be stored in Qdrant."
            )
            self._enabled = False
            return

        try:
            from google import genai
            self._genai_client = genai.Client(api_key=self._settings.GEMINI_API_KEY)
            self._embed_model = self._settings.MEMORY_EMBED_MODEL
            logger.info("Gemini embedding model ready: %s", self._embed_model)
        except Exception as exc:
            logger.exception("Gemini embedding setup failed — memory disabled: %s", exc)
            self._enabled = False

    # -------------------------------------------------------------------------
    # Async Embedding Helpers
    # -------------------------------------------------------------------------

    async def _embed_async(self, text: str, task_type: str = "retrieval_document") -> list[float] | None:
        """Embed text asynchronously using an executor."""
        if not self._enabled or not self._embed_model:
            return None

        def _sync_embed() -> list[float]:
            from google.genai import types
            result = self._genai_client.models.embed_content(
                model=self._embed_model,
                contents=text,
                config=types.EmbedContentConfig(task_type=task_type)
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
            logger.warning("Embedding failed for text snippet: %s", exc)
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

        # Build a stable, unique document ID
        timestamp_str = datetime.now(UTC).isoformat()
        id_str = hashlib.sha256(
            f"{session_id}:{role}:{text}:{timestamp_str}".encode()
        ).hexdigest()

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
                        }
                    )
                ]
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
                with_payload=True
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
                        distance=hit.score, # Qdrant returns similarity score
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
                    must=[
                        FieldCondition(
                            key="session_id",
                            match=MatchValue(value=session_id)
                        )
                    ]
                )
            )
            count = count_result.count

            if count > 0:
                await self._client.delete(
                    collection_name=self._settings.CHROMA_COLLECTION_NAME,
                    points_selector=Filter(
                        must=[
                            FieldCondition(
                                key="session_id",
                                match=MatchValue(value=session_id)
                            )
                        ]
                    )
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
