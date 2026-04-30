"""Rewrite lines 244-302 of memory_service.py to fix ARCH-04 indentation."""
from pathlib import Path

FILE = Path("src/infra/memory_service.py")
raw = FILE.read_bytes()
lines = raw.decode("utf-8").split("\r\n")

# Lines 244-302 (0-indexed 243-301) need to be replaced
CORRECT_BLOCK = [
    "        async with _get_qdrant_lock():",
    "            try:",
    "                # Using the same persist path but handled by Qdrant",
    "                from qdrant_client import AsyncQdrantClient",
    "                from qdrant_client.models import Distance, VectorParams",
    "",
    "                Path(str(self._settings.CHROMA_PERSIST_DIR)).mkdir(parents=True, exist_ok=True)",
    "",
    "                if _global_qdrant_client is None:",
    "                    _global_qdrant_client = AsyncQdrantClient(path=self._settings.CHROMA_PERSIST_DIR)",
    "",
    "                self._client = _global_qdrant_client",
    "",
    "                # Setup embedding model first \u2014 must happen before collection creation",
    "                # so we know the correct vector dimension (384 local vs 768 Gemini)",
    "                self._setup_embedding_model()",
    "",
    "                if not self._enabled:",
    "                    return",
    "",
    "                collection_name = self._settings.CHROMA_COLLECTION_NAME",
    '                embed_dim = getattr(self, "_embed_dim", 384)',
    "",
    "                # Check if collection exists with correct dimensions",
    "                if await self._client.collection_exists(collection_name=collection_name):",
    "                    # Verify dimension matches \u2014 recreate if mismatched (e.g. switched embedder)",
    "                    try:",
    "                        info = await self._client.get_collection(collection_name)",
    "                        existing_dim = info.config.params.vectors.size  # type: ignore[union-attr]",
    "                        if existing_dim != embed_dim:",
    "                            logger.warning(",
    '                                "Qdrant collection dimension mismatch (%d vs %d). "',
    '                                "Dropping and recreating collection.",',
    "                                existing_dim,",
    "                                embed_dim,",
    "                            )",
    "                            await self._client.delete_collection(collection_name)",
    "                            await self._client.create_collection(",
    "                                collection_name=collection_name,",
    "                                vectors_config=VectorParams(size=embed_dim, distance=Distance.COSINE),",
    "                            )",
    "                    except Exception:",
    "                        pass  # Collection info check failed \u2014 leave it as-is",
    "                else:",
    "                    await self._client.create_collection(",
    "                        collection_name=collection_name,",
    "                        vectors_config=VectorParams(size=embed_dim, distance=Distance.COSINE),",
    "                    )",
    "",
    "                logger.info(",
    '                    "Qdrant memory initialized \u2014 collection=%s, dim=%d, persist_dir=%s",',
    "                    collection_name,",
    "                    embed_dim,",
    "                    self._settings.CHROMA_PERSIST_DIR,",
    "                )",
    "                self._initialized = True",
    '            except Exception as exc:',
    '                logger.exception("Qdrant setup failed \u2014 memory disabled: %s", exc)',
    "                self._enabled = False",
]

# Replace lines 243-301 (0-indexed) with correct block
new_lines = lines[:243] + CORRECT_BLOCK + lines[302:]
output = "\r\n".join(new_lines)
FILE.write_bytes(output.encode("utf-8"))
print(f"Fixed: replaced {302 - 243} lines with {len(CORRECT_BLOCK)} correct lines.")
print(f"Total lines: {len(new_lines)}")
