"""
LLM Provider Management Routes.

Exposes LLM usage stats (provider usage, daily cost, remaining quota).
No auth required — informational endpoint.
"""

from fastapi import APIRouter, Depends

from src.container import get_llm_router
from src.infra.llm.router import LLMRouter


router = APIRouter(prefix="/llm", tags=["LLM"])


@router.get("/usage")
async def get_llm_usage(
    llm_router: LLMRouter = Depends(get_llm_router),
) -> dict:
    """
    Get LLM provider usage report.

    Returns today's request count per provider, daily limits,
    remaining quota, and estimated cost.
    """
    return llm_router.get_usage_report()
