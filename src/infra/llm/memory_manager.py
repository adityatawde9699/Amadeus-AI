"""
Memory Manager for Amadeus AI.

Provides recursive conversation summarization to prevent
context-window exhaustion. Runs as a FastAPI BackgroundTask.

Strategy:
  1. When message count exceeds MEMORY_SUMMARIZATION_THRESHOLD,
     compile existing summary + latest N messages.
  2. Prompt a fast LLM (Groq / Gemini) for a condensed summary.
  3. Store the new summary in ConversationSummaryORM.
  4. Prune older messages from the active context.
"""

import logging

from src.core.config import get_settings


logger = logging.getLogger(__name__)

SUMMARIZATION_SYSTEM_PROMPT = """You are a memory compression engine. Your job is to produce
a concise, factual summary of a conversation between a user and an AI assistant called Amadeus.

Rules:
- Preserve ALL user preferences, stated facts, names, dates, and ongoing tasks.
- Remove pleasantries, filler, and redundant exchanges.
- Use bullet points.
- Keep the summary under 500 words.
- If a previous summary is provided, integrate new information into it."""


async def summarize_conversation(
    messages: list[dict[str, str]],
    existing_summary: str = "",
    llm_adapter=None,
) -> str:
    """
    Generate a recursive summary of the conversation.

    Args:
        messages: List of {"role": "user"|"assistant", "content": "..."} dicts.
        existing_summary: The previous rolling summary (if any).
        llm_adapter: An LLM adapter with a ``generate()`` method.

    Returns:
        Condensed summary string.
    """
    settings = get_settings()

    if len(messages) < settings.MEMORY_SUMMARIZATION_THRESHOLD:
        return existing_summary  # Not enough messages to warrant summarization

    # Build the summarization prompt
    context_parts = []
    if existing_summary:
        context_parts.append(f"**Previous Summary:**\n{existing_summary}\n")

    context_parts.append("**New Messages:**")
    for msg in messages:
        role = msg.get("role", "user").capitalize()
        content = msg.get("content", "")
        context_parts.append(f"[{role}]: {content}")

    user_prompt = "\n".join(context_parts)

    try:
        if llm_adapter is None:
            # Late import to avoid circular deps
            from src.container import get_llm_router
            llm_adapter = get_llm_router()

        response = await llm_adapter.generate(
            system_prompt=SUMMARIZATION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        summary = response if isinstance(response, str) else str(response)
        logger.info(
            "conversation_summarized",
            extra={"input_msgs": len(messages), "summary_len": len(summary)},
        )
        return summary

    except Exception:
        logger.exception("summarization_failed")
        return existing_summary  # Fail-safe: keep old summary
