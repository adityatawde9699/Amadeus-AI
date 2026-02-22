"""
Long-Term Semantic Memory Service for Amadeus AI.

Uses ChromaDB as a local, persistent vector database and Google Gemini's
embedding API to encode and retrieve memories semantically.

Architecture:
- Every user/assistant message is embedded and stored with metadata.
- On each new query, the top-K most semantically similar past messages are
  retrieved via cosine similarity and injected into the LLM prompt.
- Graceful degradation: if ChromaDB or embeddings fail, the service logs
  the error and returns empty results (memory simply disabled, not crashed).

Usage:
    memory = ChromaMemoryService(settings)
    await memory.store(session_id="abc", role="user", text="I love astronomy")
    memories = await memory.retrieve(query="What do I enjoy?", top_k=5)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from src.core.config import Settings, get_settings


logger = logging.getLogger(__name__)


# =============================================================================
# RESULT DATACLASS
# =============================================================================

class MemoryResult:
    """A single semantic memory retrieved from the vector store."""

    __slots__ = ("session_id", "role", "text", "timestamp", "distance")

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
# CHROMA MEMORY SERVICE
# =============================================================================

class ChromaMemoryService:
    """
    Long-term semantic memory powered by ChromaDB + Gemini embeddings.

    Stores all conversation messages as vector embeddings for cross-session
    semantic retrieval. This enables the assistant to recall preferences,
    past discussions, and user-specific context from any prior session.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Any = None
        self._collection: Any = None
        self._embed_model: Any = None
        self._enabled = self._settings.CHROMA_ENABLED
        self._initialized = False

        if self._enabled:
            self._setup()

    # -------------------------------------------------------------------------
    # Setup / Initialization
    # -------------------------------------------------------------------------

    def _setup(self) -> None:
        """Initialize ChromaDB client and Gemini embedding model."""
        try:
            import chromadb  # type: ignore[import-untyped]
            from chromadb.config import Settings as ChromaSettings  # type: ignore[import-untyped]

            self._client = chromadb.PersistentClient(
                path=self._settings.CHROMA_PERSIST_DIR,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name=self._settings.CHROMA_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                "ChromaDB memory initialized — collection=%s, persist_dir=%s",
                self._settings.CHROMA_COLLECTION_NAME,
                self._settings.CHROMA_PERSIST_DIR,
            )
        except Exception as exc:
            logger.error("ChromaDB setup failed — memory disabled: %s", exc)
            self._enabled = False
            return

        self._setup_embedding_model()
        self._initialized = self._enabled

    def _setup_embedding_model(self) -> None:
        """Configure Gemini embedding model, or fall back to disabled."""
        if not self._settings.GEMINI_API_KEY:
            logger.warning(
                "GEMINI_API_KEY not set — semantic memory embedding disabled. "
                "Messages will not be stored in ChromaDB."
            )
            self._enabled = False
            return

        try:
            import google.generativeai as genai  # type: ignore[import-untyped]
            genai.configure(api_key=self._settings.GEMINI_API_KEY)
            self._embed_model = self._settings.MEMORY_EMBED_MODEL
            logger.info("Gemini embedding model ready: %s", self._embed_model)
        except Exception as exc:
            logger.error("Gemini embedding setup failed — memory disabled: %s", exc)
            self._enabled = False

    # -------------------------------------------------------------------------
    # Embedding Helper
    # -------------------------------------------------------------------------

    def _embed(self, text: str) -> list[float] | None:
        """
        Embed text synchronously using Gemini's embed_content API.

        Returns None on failure so callers can skip storage gracefully.
        """
        if not self._enabled or not self._embed_model:
            return None
        try:
            import google.generativeai as genai  # type: ignore[import-untyped]
            result = genai.embed_content(
                model=self._embed_model,
                content=text,
                task_type="retrieval_document",
            )
            return result["embedding"]
        except Exception as exc:
            logger.warning("Embedding failed for text snippet: %s", exc)
            return None

    def _embed_query(self, text: str) -> list[float] | None:
        """Embed text for a query (retrieval_query task type)."""
        if not self._enabled or not self._embed_model:
            return None
        try:
            import google.generativeai as genai  # type: ignore[import-untyped]
            result = genai.embed_content(
                model=self._embed_model,
                content=text,
                task_type="retrieval_query",
            )
            return result["embedding"]
        except Exception as exc:
            logger.warning("Query embedding failed: %s", exc)
            return None

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def store(self, session_id: str, role: str, text: str) -> bool:
        """
        Embed and persist a message into the vector store.

        Args:
            session_id: The current conversation session identifier.
            role: 'user' or 'assistant'.
            text: The message content to store.

        Returns:
            True if stored successfully, False otherwise.
        """
        if not self._enabled:
            return False

        # Run blocking embedding + ChromaDB write in a thread
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._store_sync, session_id, role, text)

    def _store_sync(self, session_id: str, role: str, text: str) -> bool:
        """Synchronous store implementation (runs in executor thread)."""
        embedding = self._embed(text)
        if embedding is None:
            return False

        # Build a stable, unique document ID
        timestamp_str = datetime.now(timezone.utc).isoformat()
        doc_id = hashlib.sha256(
            f"{session_id}:{role}:{text}:{timestamp_str}".encode()
        ).hexdigest()[:32]

        try:
            self._collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[text],
                metadatas=[{
                    "session_id": session_id,
                    "role": role,
                    "timestamp": timestamp_str,
                }],
            )
            logger.debug("Memory stored — doc_id=%s, role=%s", doc_id, role)
            return True
        except Exception as exc:
            logger.warning("ChromaDB upsert failed: %s", exc)
            return False

    async def retrieve(self, query: str, top_k: int = 5) -> list[MemoryResult]:
        """
        Semantically retrieve the most relevant past messages for a query.

        Args:
            query: The user's current input or topic to search for.
            top_k: Maximum number of past memories to return.

        Returns:
            List of MemoryResult objects, sorted by relevance (closest first).
        """
        if not self._enabled:
            return []

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._retrieve_sync, query, top_k)

    def _retrieve_sync(self, query: str, top_k: int) -> list[MemoryResult]:
        """Synchronous retrieve implementation (runs in executor thread)."""
        embedding = self._embed_query(query)
        if embedding is None:
            return []

        try:
            results = self._collection.query(
                query_embeddings=[embedding],
                n_results=min(top_k, max(1, self._collection.count())),
                include=["documents", "metadatas", "distances"],
            )

            memories: list[MemoryResult] = []
            if not results or not results.get("documents"):
                return memories

            documents = results["documents"][0]
            metadatas = results["metadatas"][0]
            distances = results["distances"][0]

            for doc, meta, dist in zip(documents, metadatas, distances):
                memories.append(
                    MemoryResult(
                        session_id=meta.get("session_id", ""),
                        role=meta.get("role", "unknown"),
                        text=doc,
                        timestamp=meta.get("timestamp", ""),
                        distance=float(dist),
                    )
                )

            logger.debug("Retrieved %d memories for query snippet=%r", len(memories), query[:40])
            return memories

        except Exception as exc:
            logger.warning("ChromaDB query failed: %s", exc)
            return []

    async def clear_session(self, session_id: str) -> int:
        """
        Remove all stored memories for a specific session.

        Args:
            session_id: The session to purge.

        Returns:
            Number of documents deleted.
        """
        if not self._enabled:
            return 0

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._clear_session_sync, session_id)

    def _clear_session_sync(self, session_id: str) -> int:
        """Synchronous clear (runs in executor thread)."""
        try:
            existing = self._collection.get(
                where={"session_id": session_id},
                include=[],
            )
            ids_to_delete = existing.get("ids", [])
            if ids_to_delete:
                self._collection.delete(ids=ids_to_delete)
                logger.info("Cleared %d memories for session=%s", len(ids_to_delete), session_id[:8])
            return len(ids_to_delete)
        except Exception as exc:
            logger.warning("ChromaDB session clear failed: %s", exc)
            return 0

    @property
    def is_enabled(self) -> bool:
        """True if the memory service is active and ready."""
        return self._enabled and self._initialized

    @property
    def memory_count(self) -> int:
        """Total number of stored memories across all sessions."""
        if not self._enabled or not self._collection:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0

    def format_for_prompt(self, memories: list[MemoryResult], max_chars: int = 1000) -> str:
        """
        Format retrieved memories as a readable string for LLM injection.

        Args:
            memories: List of MemoryResult from retrieve().
            max_chars: Soft character cap to avoid bloating the prompt.

        Returns:
            Formatted multi-line string for the system prompt.
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
