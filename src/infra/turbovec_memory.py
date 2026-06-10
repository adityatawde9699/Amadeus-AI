"""
Turbovec Memory Service for Amadeus AI.

Uses Turbovec for high-performance, in-process 4-bit quantized vector search,
backed by an aiosqlite database for storing the JSON payloads.
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
from opentelemetry import trace


try:
    import numpy as np
    import turbovec
except ImportError:
    turbovec = None

from src.core.config import Settings, get_settings
from src.infra.memory_service import MemoryResult


logger = logging.getLogger(__name__)

# Global instances to prevent concurrent file locks in memory
_global_turbovec_index = None
_global_sqlite_pool = None
_turbovec_init_lock = None

def _get_init_lock() -> asyncio.Lock:
    global _turbovec_init_lock
    if _turbovec_init_lock is None:
        _turbovec_init_lock = asyncio.Lock()
    return _turbovec_init_lock

class TurbovecMemoryService:
    """
    Long-term semantic memory powered by Turbovec + local aiosqlite payload store.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._enabled = self._settings.MEMORY_ENABLED
        self._initialized = False
        self._embed_model: Any = None
        self._local_embed_model: Any = None
        self._use_local_embed = False
        self._embed_dim = 768  # default for Gemini

        # Paths
        self._persist_dir = Path(self._settings.MEMORY_PERSIST_DIR)
        self._index_path = self._persist_dir / "turbovec_memory.tvim"
        self._db_path = self._persist_dir / "turbovec_payloads.sqlite"
        self._index = None
        self._db = None

    async def initialize(self) -> None:
        if not self._enabled:
            return

        if turbovec is None:
            logger.warning("turbovec not installed, memory disabled.")
            self._enabled = False
            return

        async with _get_init_lock():
            if self._initialized:
                return

            try:
                self._persist_dir.mkdir(parents=True, exist_ok=True)

                # Setup embedding model first to get dimension
                await self._setup_embedding_model()

                if not self._enabled:
                    return

                # Init SQLite payload DB
                self._db = await aiosqlite.connect(self._db_path)
                await self._db.execute("""
                    CREATE TABLE IF NOT EXISTS memory_payloads (
                        id INTEGER PRIMARY KEY,
                        session_id TEXT,
                        role TEXT,
                        text TEXT,
                        timestamp TEXT,
                        type TEXT,
                        subtype TEXT,
                        importance REAL,
                        source TEXT,
                        trust_score REAL,
                        access_count INTEGER,
                        hash TEXT UNIQUE
                    )
                """)
                await self._db.execute("CREATE INDEX IF NOT EXISTS idx_session ON memory_payloads(session_id)")
                await self._db.execute("CREATE INDEX IF NOT EXISTS idx_text ON memory_payloads(text)")
                await self._db.commit()

                # Init Turbovec
                global _global_turbovec_index
                if _global_turbovec_index is None:
                    if self._index_path.exists():
                        _global_turbovec_index = turbovec.IdMapIndex.load(str(self._index_path))
                    else:
                        _global_turbovec_index = turbovec.IdMapIndex(dim=self._embed_dim, bit_width=4)

                self._index = _global_turbovec_index

                logger.info("Turbovec initialized, dim=%d, size=%d", self._embed_dim, len(self._index))
                self._initialized = True
            except Exception as e:
                logger.exception("Turbovec setup failed: %s", e)
                self._enabled = False

    async def _setup_embedding_model(self) -> None:
        model_name = self._settings.EMBED_MODEL_NAME
        try:
            from src.infra.model_manager import ModelManager
            mm = ModelManager(self._settings)
            load_path, local_dir = mm.resolve_embed_model()
        except Exception:
            load_path, local_dir = model_name, None

        try:
            from sentence_transformers import SentenceTransformer
            self._local_embed_model = SentenceTransformer(load_path)
            self._embed_dim = self._local_embed_model.get_embedding_dimension() or 384
            self._use_local_embed = True
            return
        except ImportError:
            pass
        except Exception as exc:
            logger.warning("Local embed model failed: %s", exc)

        self._use_local_embed = False
        if not self._settings.GEMINI_API_KEY:
            self._enabled = False
            return

        try:
            from google import genai
            self._genai_client = genai.Client(api_key=self._settings.GEMINI_API_KEY)
            self._embed_model = self._settings.MEMORY_EMBED_MODEL
            self._embed_dim = 768
        except Exception as exc:
            logger.exception("Gemini embed setup failed: %s", exc)
            self._enabled = False

    async def _embed_async(self, text: str, task_type: str = "retrieval_document") -> list[float] | None:
        if not self._enabled:
            return None

        if self._use_local_embed:
            try:
                loop = asyncio.get_running_loop()
                def _local_embed():
                    return self._local_embed_model.encode(text, show_progress_bar=False).tolist()
                return await loop.run_in_executor(None, _local_embed)
            except Exception as exc:
                logger.warning("Local embedding failed: %s", exc)
                return None

        if not self._embed_model:
            return None

        def _sync_embed():
            from google.genai import types
            result = self._genai_client.models.embed_content(
                model=self._embed_model,
                contents=text,
                config=types.EmbedContentConfig(task_type=task_type),
            )
            if not result.embeddings:
                return []
            return result.embeddings[0].values or []

        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, _sync_embed)
        except Exception as exc:
            logger.warning("Gemini embedding failed: %s", exc)
            return None

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
        if not self._enabled or not self._initialized:
            return False

        assert self._db is not None
        assert self._index is not None

        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("TurbovecMemoryService.store") as span:
            if subtype == "identity":
                importance = 1.0
            elif importance == 0.5:
                importance = 0.6 if role == "user" else 0.7

            trust_score = 0.8 if source == "user" else 0.5

            embedding = await self._embed_async(text, "retrieval_document")
            if embedding is None:
                return False

            raw_key = f"{session_id}:{role}:{text}"
            timestamp_str = datetime.now(UTC).isoformat()

            try:
                # Contradiction Resolution
                if subtype == "identity":
                    async with self._db.execute(
                        "SELECT id FROM memory_payloads WHERE subtype=? AND session_id=?",
                        ("identity", session_id)
                    ) as cursor:
                        rows = await cursor.fetchall()
                        if rows:
                            ids_to_check = [r[0] for r in rows]
                            # Let turbovec find similarities
                            ids_arr = np.array(ids_to_check, dtype=np.uint64)
                            queries = np.array([embedding], dtype=np.float32)
                            scores, ret_ids = self._index.search(queries, k=3, allowlist=ids_arr)

                            to_delete = []
                            for i, score in enumerate(scores[0]):
                                if score > 0.90:
                                    to_delete.append(int(ret_ids[0][i]))

                            if to_delete:
                                for did in to_delete:
                                    self._index.remove(np.uint64(did))
                                    await self._db.execute("DELETE FROM memory_payloads WHERE id=?", (did,))
                                await self._db.commit()

                # Check if hash already exists to avoid duplicates
                async with self._db.execute("SELECT id FROM memory_payloads WHERE hash=?", (raw_key,)) as cursor:
                    existing = await cursor.fetchone()
                    if existing:
                        db_id = existing[0]
                        # Remove existing from index so we can update it
                        if self._index.contains(np.uint64(db_id)):
                            self._index.remove(np.uint64(db_id))
                    else:
                        # Insert new
                        await self._db.execute(
                            """INSERT INTO memory_payloads 
                               (session_id, role, text, timestamp, type, subtype, importance, source, trust_score, access_count, hash) 
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                            (session_id, role, text, timestamp_str, type, subtype, importance, source, trust_score, raw_key)
                        )
                        await self._db.commit()
                        async with self._db.execute("SELECT last_insert_rowid()") as cursor2:
                            db_id = (await cursor2.fetchone())[0]

                # Add to Turbovec
                vec_arr = np.array([embedding], dtype=np.float32)
                id_arr = np.array([db_id], dtype=np.uint64)
                self._index.add_with_ids(vec_arr, id_arr)

                # Save to disk
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._index.write, str(self._index_path))

                return True
            except Exception as exc:
                logger.warning("Turbovec store failed: %s", exc)
                return False

    async def retrieve(self, query: str, top_k: int = 5) -> list[MemoryResult]:
        if not self._enabled or not self._initialized:
            return []

        assert self._db is not None
        assert self._index is not None

        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("TurbovecMemoryService.retrieve"):
            embedding = await self._embed_async(query, "retrieval_query")
            if embedding is None:
                return []

            try:
                queries = np.array([embedding], dtype=np.float32)
                scores, ret_ids = self._index.search(queries, k=top_k * 2)

                if not len(ret_ids) or not len(ret_ids[0]):
                    return []

                result_ids = [int(i) for i in ret_ids[0]]
                result_scores = {int(ret_ids[0][i]): float(scores[0][i]) for i in range(len(result_ids))}

                # Fetch payloads
                placeholders = ",".join(["?"] * len(result_ids))
                query_sql = f"SELECT id, session_id, role, text, timestamp, type, subtype, importance, source, access_count FROM memory_payloads WHERE id IN ({placeholders})"

                memories = []
                now = datetime.now(UTC)
                tau_seconds = 7 * 24 * 3600

                async with self._db.execute(query_sql, result_ids) as cursor:
                    async for row in cursor:
                        db_id, session_id, role, text, timestamp_str, type_, subtype, importance, source, access_count = row
                        similarity = result_scores.get(db_id, 0.0)

                        if similarity < 0.65:
                            continue

                        recency_decay = 0.0
                        if timestamp_str and subtype != "identity":
                            try:
                                mem_time = datetime.fromisoformat(timestamp_str)
                                if mem_time.tzinfo is None:
                                    mem_time = mem_time.replace(tzinfo=UTC)
                                time_delta = (now - mem_time).total_seconds()
                                recency_decay = math.exp(-max(0, time_delta) / tau_seconds)
                            except:
                                recency_decay = 0.5
                        elif subtype == "identity":
                            importance = 1.0
                            recency_decay = 1.0

                        access_boost = min(0.1, access_count * 0.01)
                        weighted_score = (0.6 * similarity) + (0.25 * importance) + (0.15 * recency_decay) + access_boost

                        memories.append(
                            MemoryResult(
                                session_id=session_id, role=role, text=text, timestamp=timestamp_str,
                                distance=similarity, type=type_, subtype=subtype, importance=importance,
                                source=source, score=weighted_score
                            )
                        )

                memories.sort(key=lambda x: x.score, reverse=True)
                memories = memories[:top_k]

                if memories:
                    asyncio.create_task(self._increment_access_counts([m.text for m in memories]))

                return memories
            except Exception as exc:
                logger.warning("Turbovec retrieve failed: %s", exc)
                return []

    async def clear_session(self, session_id: str) -> int:
        if not self._enabled or not self._initialized:
            return 0
            
        assert self._db is not None
        assert self._index is not None
        
        try:
            async with self._db.execute("SELECT id FROM memory_payloads WHERE session_id=?", (session_id,)) as cursor:
                rows = await cursor.fetchall()
                if not rows:
                    return 0

                for r in rows:
                    if self._index.contains(np.uint64(r[0])):
                        self._index.remove(np.uint64(r[0]))

                await self._db.execute("DELETE FROM memory_payloads WHERE session_id=?", (session_id,))
                await self._db.commit()

                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._index.write, str(self._index_path))

                return len(rows)
        except Exception as exc:
            logger.warning("Turbovec clear_session failed: %s", exc)
            return 0

    async def delete_by_text(self, text: str) -> int:
        if not self._enabled or not self._initialized:
            return 0
            
        assert self._db is not None
        assert self._index is not None
        
        try:
            async with self._db.execute("SELECT id FROM memory_payloads WHERE text=?", (text,)) as cursor:
                rows = await cursor.fetchall()
                if not rows:
                    return 0

                for r in rows:
                    if self._index.contains(np.uint64(r[0])):
                        self._index.remove(np.uint64(r[0]))

                await self._db.execute("DELETE FROM memory_payloads WHERE text=?", (text,))
                await self._db.commit()

                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._index.write, str(self._index_path))

                return len(rows)
        except Exception as exc:
            logger.warning("Turbovec delete_by_text failed: %s", exc)
            return 0

    async def prune_stale_memories(self, session_id: str, older_than_days: int = 90) -> int:
        if not self._enabled or not self._initialized:
            return 0
            
        assert self._db is not None
        assert self._index is not None
        
        try:
            now = datetime.now(UTC)
            cutoff_seconds = older_than_days * 24 * 3600

            async with self._db.execute("SELECT id, timestamp FROM memory_payloads WHERE session_id=? AND subtype != 'identity'", (session_id,)) as cursor:
                rows = await cursor.fetchall()

            to_delete = []
            for db_id, timestamp_str in rows:
                if timestamp_str:
                    try:
                        mem_time = datetime.fromisoformat(timestamp_str)
                        if mem_time.tzinfo is None:
                            mem_time = mem_time.replace(tzinfo=UTC)
                        age = (now - mem_time).total_seconds()
                        if age > cutoff_seconds:
                            to_delete.append(db_id)
                    except:
                        pass

            if to_delete:
                for db_id in to_delete:
                    if self._index.contains(np.uint64(db_id)):
                        self._index.remove(np.uint64(db_id))

                placeholders = ",".join(["?"] * len(to_delete))
                await self._db.execute(f"DELETE FROM memory_payloads WHERE id IN ({placeholders})", to_delete)
                await self._db.commit()

                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._index.write, str(self._index_path))

            return len(to_delete)
        except Exception as exc:
            logger.warning("Turbovec prune_stale_memories failed: %s", exc)
            return 0

    @property
    def is_enabled(self) -> bool:
        return self._enabled and self._initialized

    @property
    def memory_count(self) -> int:
        if not self._enabled or not self._initialized or not self._index:
            return 0
        return len(self._index)

    async def get_memory_count(self) -> int:
        return self.memory_count

    def format_for_prompt(self, memories: list[MemoryResult], max_chars: int = 1000) -> str:
        if not memories:
            return ""
        lines = []
        char_count = 0
        for i, mem in enumerate(memories, 1):
            line = f"{i}. {mem.text}"
            if char_count + len(line) > max_chars:
                break
            lines.append(line)
            char_count += len(line)
        return "\n".join(lines)

    async def _increment_access_counts(self, texts: list[str]) -> None:
        if not self._enabled or not self._initialized or not texts:
            return
            
        assert self._db is not None
        
        try:
            unique_texts = list(dict.fromkeys(texts))
            placeholders = ",".join(["?"] * len(unique_texts))
            await self._db.execute(f"UPDATE memory_payloads SET access_count = access_count + 1 WHERE text IN ({placeholders})", unique_texts)
            await self._db.commit()
        except Exception as exc:
            logger.debug("Failed to increment access counts: %s", exc)
