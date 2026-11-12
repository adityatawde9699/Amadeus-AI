
import asyncio
import sys
from pathlib import Path


sys.path.append(str(Path(__file__).parent.parent))

from src.app.services.semantic_router import UnifiedSemanticRouter
from src.app.services.tool_registry import ToolRegistry
from src.infra.tools.base import Tool, ToolCategory


async def test_routing():
    registry = ToolRegistry()

    async def dummy_weather(**kwargs):
        return "Sunny"

    async def dummy_cpu(**kwargs):
        return "CPU: 20%"

    registry.register(Tool(
        name="get_weather",
        function=dummy_weather,
        description="Get current weather conditions and forecast for a city or location",
        category=ToolCategory.INFORMATION
    ))
    registry.register(Tool(
        name="get_cpu_usage",
        function=dummy_cpu,
        description="Check current CPU usage, processor load, and system performance metrics",
        category=ToolCategory.SYSTEM
    ))

    router = UnifiedSemanticRouter(registry)  # uses default threshold (0.38)
    router.build_index()

    # Debug: show top-3 scores for each query
    import numpy as np

    queries = [
        "What's the weather in Tokyo?",
        "Hello Amadeus, how are you today?",
        "Solve this complex quantum equation: H*psi = E*psi",
        "hi",
        "check my system cpu usage"
    ]

    print("\n--- Routing Results (with top-3 scores) ---")
    for q in queries:
        q_vec = router._embed_model.encode(q, normalize_embeddings=True, show_progress_bar=False)
        scores = router._matrix @ q_vec
        top3_idx = np.argsort(scores)[::-1][:3]

        print(f"\nQuery: '{q}'")
        for idx in top3_idx:
            print(f"  [{router._types[idx]:8s}] {router._labels[idx]:30s}  score={scores[idx]:.4f}")

        intent, detail = router.route(q)
        print(f"  => ROUTED TO: {intent}  (Detail: {detail})")


if __name__ == "__main__":
    # Force UTF-8 output on Windows
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(test_routing())
