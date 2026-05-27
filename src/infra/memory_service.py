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

from opentelemetry import trace

from src.core.config import Settings, get_settings
from src.infra.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerOpenException


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



# =============================================================================
# QDRANT MEMORY SERVICE
# =============================================================================


# Global cache for the Qdrant client to avoid FileLock collisions
_global_qdrant_client = None
# ARCH-04: Lock to prevent concurrent initialization races.
# Multiple simultaneous calls to initialize() (e.g. during startup under load)
# could each create an AsyncQdrantClient writing to the same path, causing
# FileLock collisions. The lock ensures only the first caller initialises.
_qdrant_init_lock: asyncio.Lock | None = None


def _get_qdrant_lock() -> asyncio.Lock:
    """Lazily create the init lock once an event loop is running."""
    global _qdrant_init_lock
    if _qdrant_init_lock is None:
        _qdrant_init_lock = asyncio.Lock()
    return _qdrant_init_lock


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
        self._circuit_breaker = CircuitBreaker("qdrant", failure_threshold=3, recovery_timeout=60)



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
        # ARCH-04: Acquire init lock so concurrent initialize() calls don't
        # each spin up a separate AsyncQdrantClient on the same path.
        async with _get_qdrant_lock():
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
          1. Local MODEL_DIR/embed/<model> (auto-downloaded on first run)
          2. HuggingFace cache (fallback if ModelManager can't resolve)
          3. Gemini embedding API (cloud fallback, requires API key + quota)
        """
        model_name = self._settings.EMBED_MODEL_NAME

        # Resolve local path via ModelManager
        try:
            from src.infra.model_manager import ModelManager
            mm = ModelManager(self._settings)
            load_path, local_dir = mm.resolve_embed_model()
        except Exception as exc:
            logger.warning("ModelManager failed: %s — falling back to HF id", exc)
            load_path, local_dir = model_name, None

        # --- Try local sentence-transformers ---
        try:
            from sentence_transformers import SentenceTransformer

            self._local_embed_model = SentenceTransformer(load_path)
            self._embed_dim = self._local_embed_model.get_sentence_embedding_dimension() or 384
            self._use_local_embed = True
            logger.info(
                "Local embed model loaded: %s → %s (dim=%d)",
                model_name, load_path, self._embed_dim,
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

        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("QdrantMemoryService.store") as span:
            span.set_attribute("memory.role", role)
            span.set_attribute("memory.subtype", subtype)
            
            # Identity memories have fixed high importance
            if subtype == "identity":
                importance = 1.0
            elif importance == 0.5:
                # Auto-compute importance
                if role == "user":
                    importance = 0.6 if type == "memory" else 0.4
                elif role == "system":
                    importance = 0.7
                    
            trust_score = 0.8 if source == "user" else 0.5
    
            embedding = await self._embed_async(text, "retrieval_document")
        if embedding is None:
            return False

        # P6-T7: Build a stable, CONTENT-BASED point ID so that identical
        # (session, role, text) tuples always map to the same Qdrant slot.
        # This makes upsert idempotent — flooding the same text n times
        # only overwrites the same vector entry instead of creating n copies.
        raw_key = f"{session_id}:{role}:{text}"
        id_str = str(uuid.uuid5(uuid.NAMESPACE_OID, raw_key))
        timestamp_str = datetime.now(UTC).isoformat()

        # Contradiction Resolution: If this is an identity fact, check for existing contradictory/duplicate facts.
        if subtype == "identity":
            try:
                from qdrant_client.models import Filter, FieldCondition, MatchValue
                existing_hits = await self._circuit_breaker.call(
                    self._client.search,
                    collection_name=self._settings.CHROMA_COLLECTION_NAME,
                    query_vector=embedding,
                    limit=3,
                    query_filter=Filter(
                        must=[
                            FieldCondition(key="subtype", match=MatchValue(value="identity")),
                            FieldCondition(key="session_id", match=MatchValue(value=session_id)),
                        ]
                    )
                )
                to_delete = []
                for hit in existing_hits:
                    # If similarity is > 0.90, we consider it a duplicate/contradiction of the same topic.
                    if hit.score > 0.90 and hit.id != id_str:
                        to_delete.append(hit.id)
                
                if to_delete:
                    await self._circuit_breaker.call(
                        self._client.delete,
                        collection_name=self._settings.CHROMA_COLLECTION_NAME,
                        points_selector=to_delete
                    )
                    logger.info("Resolved contradiction: deleted %d existing identity memories.", len(to_delete))
            except Exception as e:
                logger.warning("Contradiction resolution failed: %s", e)

        try:
            from qdrant_client.models import PointStruct

            await self._circuit_breaker.call(
                self._client.upsert,
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
                            "trust_score": trust_score,
                            "access_count": 0,
                        },
                    )
                ],
            )
            span.set_attribute("memory.stored", True)
            logger.debug("Memory stored — id=%s, role=%s", id_str[:8], role)



            return True
        except CircuitBreakerOpenException:
            logger.warning("Qdrant circuit is OPEN. Skipping store.")
            return False
        except Exception as exc:
            logger.warning("Qdrant upsert failed: %s", exc)
            # P7-Chaos01: Increment memory error counter for Prometheus alerting
            try:
                from src.infra.metrics import amadeus_memory_errors_total
                amadeus_memory_errors_total.labels(operation="upsert").inc()
            except Exception:
                pass
            span.set_attribute("memory.stored", False)
            span.set_attribute("memory.error", str(exc))
            return False

    async def retrieve(self, query: str, top_k: int = 5) -> list[MemoryResult]:
        """
        Semantic retrieval:
          Qdrant (async network call, full historical search).
        """
        if not self._enabled or not self._initialized:
            return []

        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("QdrantMemoryService.retrieve") as span:
            span.set_attribute("memory.top_k", top_k)
            
            embedding = await self._embed_async(query, "retrieval_query")
            if embedding is None:
                return []
    
            # --- Qdrant search ---
        try:
            import math

            results = await self._circuit_breaker.call(
                self._client.search,
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

                # Access frequency boost
                access_count = payload.get("access_count", 0)
                access_boost = min(0.1, access_count * 0.01)

                weighted_score = (0.6 * similarity) + (0.25 * importance) + (0.15 * recency_decay) + access_boost

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
            
            span.set_attribute("memory.retrieved_count", len(memories))
            logger.debug("Qdrant: retrieved %d weighted memories (L1 miss).", len(memories))
            
            # Fire and forget task to increment access_count for these memories
            if memories:
                asyncio.create_task(self._increment_access_counts([m.text for m in memories]))
                
            return memories

        except CircuitBreakerOpenException:
            logger.warning("Qdrant circuit is OPEN. Skipping retrieve.")
            return []
        except Exception as exc:
            logger.warning("Qdrant search failed (client type=%s): %s", type(self._client), exc)
            # P7-Chaos01: Increment memory error counter for Prometheus alerting
            try:
                from src.infra.metrics import amadeus_memory_errors_total
                amadeus_memory_errors_total.labels(operation="search").inc()
            except Exception:
                pass
            span.record_exception(exc)
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

    async def delete_by_text(self, text: str) -> int:
        """
        Remove memories that exactly match the given text.
        Useful for the agent's 'forget_core_memory' tool.
        """
        if not self._enabled or not self._initialized:
            return 0
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue
            count_result = await self._client.count(
                collection_name=self._settings.CHROMA_COLLECTION_NAME,
                count_filter=Filter(
                    must=[FieldCondition(key="text", match=MatchValue(value=text))]
                ),
            )
            count = count_result.count
            if count > 0:
                await self._client.delete(
                    collection_name=self._settings.CHROMA_COLLECTION_NAME,
                    points_selector=Filter(
                        must=[FieldCondition(key="text", match=MatchValue(value=text))]
                    ),
                )
                logger.info("Deleted %d memories matching text='%s'", count, text[:20])
            return int(count)
        except Exception as exc:
            logger.warning("Qdrant delete_by_text failed: %s", exc)
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

    async def _increment_access_counts(self, texts: list[str]) -> None:
        """Increment access_count for the given memory texts (used by fire-and-forget task)."""
        if not self._enabled or not self._initialized:
            return
            
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue
            for text in texts:
                # Need to find the point by text and update its payload
                results = await self._client.search(
                    collection_name=self._settings.CHROMA_COLLECTION_NAME,
                    query_vector=[0.0]*getattr(self, "_embed_dim", 384), # Dummy vector if using text filter
                    query_filter=Filter(must=[FieldCondition(key="text", match=MatchValue(value=text))]),
                    limit=1,
                    with_payload=True
                )
                if results:
                    hit = results[0]
                    current_count = hit.payload.get("access_count", 0) if hit.payload else 0
                    await self._client.set_payload(
                        collection_name=self._settings.CHROMA_COLLECTION_NAME,
                        payload={"access_count": current_count + 1},
                        points=[hit.id]
                    )
        except Exception as exc:
            logger.debug("Failed to increment access counts: %s", exc)

    async def prune_stale_memories(self, session_id: str, older_than_days: int = 90) -> int:
        """
        Remove memories for a session that are older than X days and not marked as identity.
        """
        if not self._enabled or not self._initialized:
            return 0
            
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue
            
            # Fetch all memories for session to check timestamps
            results = await self._client.scroll(
                collection_name=self._settings.CHROMA_COLLECTION_NAME,
                scroll_filter=Filter(must=[FieldCondition(key="session_id", match=MatchValue(value=session_id))]),
                limit=10000,
                with_payload=True
            )
            
            points = results[0]
            now = datetime.now(UTC)
            stale_ids = []
            
            for point in points:
                payload = point.payload or {}
                subtype = payload.get("subtype", "")
                if subtype == "identity":
                    continue
                    
                timestamp_str = payload.get("timestamp", "")
                if timestamp_str:
                    try:
                        mem_time = datetime.fromisoformat(timestamp_str)
                        if mem_time.tzinfo is None:
                            mem_time = mem_time.replace(tzinfo=UTC)
                        days_old = (now - mem_time).total_seconds() / (24 * 3600)
                        if days_old > older_than_days:
                            stale_ids.append(point.id)
                    except Exception:
                        pass
                        
            if stale_ids:
                await self._client.delete(
                    collection_name=self._settings.CHROMA_COLLECTION_NAME,
                    points_selector=stale_ids
                )
                logger.info("Pruned %d stale memories for session=%s", len(stale_ids), session_id)
                
            return len(stale_ids)
        except Exception as exc:
            logger.warning("Failed to prune stale memories: %s", exc)
            return 0
