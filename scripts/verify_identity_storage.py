"""
Verification script for Amadeus AI Core Identity and Memory.

Checks if Tier 2 (KG) and Tier 3 (Semantic) memories are correctly stored.
"""

import asyncio
import logging
import json
from src.infra.memory_service import QdrantMemoryService
from src.infra.knowledge_graph import KnowledgeGraphService
from src.core.config import get_settings

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

async def verify_storage():
    settings = get_settings()
    
    # 1. Verify Semantic Memory (Tier 3)
    logger.info("--- Verifying Semantic Memory ---")
    memory_service = QdrantMemoryService(settings=settings)
    await memory_service.initialize()
    
    if memory_service.is_enabled:
        methods = [m for m in dir(memory_service._client) if not m.startswith("_")][15:45]
        logger.info("Qdrant Client Methods [15:45]: %s", methods)
        # Search for the core identity entry
        memories = await memory_service.retrieve("Core Identity & Origin", top_k=1)
        if memories:
            mem = memories[0]
            logger.info("Found semantic memory: Subtype=%s, Score=%.4f", mem.subtype, mem.score)
            logger.info("Content Snippet: %s...", mem.text[:100])
            if mem.subtype == "identity" and "Core Identity & Origin" in mem.text:
                logger.info("SUCCESS: Semantic Identity stored correctly.")
            else:
                logger.warning("WARNING: Found memory but subtype or content doesn't match expectation.")
        else:
            logger.error("FAILURE: No relevant semantic memory found.")
    else:
        logger.error("Memory service is not enabled.")

    # 2. Verify Knowledge Graph (Tier 2)
    logger.info("\n--- Verifying Knowledge Graph ---")
    kg_service = KnowledgeGraphService()
    
    # Test retrieval of specific facts
    facts = await kg_service.retrieve_triples("Aditya S Tawde", limit=10)
    if facts:
        logger.info("Found %d triples related to 'Aditya S Tawde':", len(facts))
        for fact in facts:
            logger.info("  %s", fact)
        
        expected_fact = "(Aditya S Tawde) —[created]→ (Amadeus)"
        if any(expected_fact in f for f in facts):
            logger.info("SUCCESS: KG triple found correctly.")
        else:
            logger.warning("Expected fact '%s' not found in results.", expected_fact)
    else:
        logger.error("FAILURE: No triples found for 'Aditya S Tawde'.")

if __name__ == "__main__":
    asyncio.run(verify_storage())
