"""
Prometheus metrics for Amadeus AI.

All application-level metrics are defined here so that both the
infrastructure layer (tools, services) and the API layer (server.py)
can import from a single source without creating circular dependencies.

Usage
-----
    from src.infra.metrics import (
        amadeus_llm_calls_total,
        amadeus_tool_calls_total,
        amadeus_cache_hit_rate,
        amadeus_llm_cost_usd,
    )
    amadeus_llm_calls_total.labels(provider="gemini").inc()
"""

from prometheus_client import Counter, Gauge


# ---------------------------------------------------------------------------
# LLM Metrics
# ---------------------------------------------------------------------------

try:
    amadeus_llm_calls_total: Counter = Counter(
        "amadeus_llm_calls_total",
        "Total number of LLM API calls made by provider",
        ["provider"],
    )
except ValueError:
    # Already registered — happens on uvicorn auto-reload
    from prometheus_client import REGISTRY
    amadeus_llm_calls_total = REGISTRY._names_to_collectors.get(  # type: ignore[assignment]
        "amadeus_llm_calls_total"
    )

try:
    amadeus_llm_cost_usd: Gauge = Gauge(
        "amadeus_llm_cost_usd",
        "Estimated cumulative LLM cost in USD",
    )
except ValueError:
    from prometheus_client import REGISTRY
    amadeus_llm_cost_usd = REGISTRY._names_to_collectors.get(  # type: ignore[assignment]
        "amadeus_llm_cost_usd"
    )


# ---------------------------------------------------------------------------
# Tool Metrics
# ---------------------------------------------------------------------------

try:
    amadeus_tool_calls_total: Counter = Counter(
        "amadeus_tool_calls_total",
        "Total number of tool invocations by tool name",
        ["tool_name"],
    )
except ValueError:
    from prometheus_client import REGISTRY
    amadeus_tool_calls_total = REGISTRY._names_to_collectors.get(  # type: ignore[assignment]
        "amadeus_tool_calls_total"
    )


# ---------------------------------------------------------------------------
# Cache Metrics
# ---------------------------------------------------------------------------

try:
    amadeus_cache_hit_rate: Gauge = Gauge(
        "amadeus_cache_hit_rate",
        "Current LLM/tool result cache hit rate as a percentage (0–100)",
    )
except ValueError:
    from prometheus_client import REGISTRY
    amadeus_cache_hit_rate = REGISTRY._names_to_collectors.get(  # type: ignore[assignment]
        "amadeus_cache_hit_rate"
    )
