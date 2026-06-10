"""
Agent Profiles for the Agentic Mixture-of-Experts (MoE) architecture.

Each AgentProfile defines a specialized sub-agent that the Supervisor Router
can activate. By constraining each expert to a small subset of tools and a
focused system prompt, we dramatically reduce the LLM context window and
improve zero-shot accuracy.

Usage:
    from src.core.domain.agent_profiles import AGENT_PROFILES, get_profile_for_category

    profile = get_profile_for_category(ToolCategory.COMMUNICATION)
    # -> AgentProfile(name="email_expert", ...)
"""

from __future__ import annotations

from dataclasses import dataclass

from src.infra.tools.base import ToolCategory


@dataclass(frozen=True)
class AgentProfile:
    """Defines a specialized sub-agent expert for MoE routing.

    Attributes:
        name: Unique identifier for the expert (e.g. "email_expert").
        display_name: Human-readable name for logging/UI.
        description: Rich description used for semantic embedding matching.
        categories: ToolCategory enums this expert owns.
        system_prompt_preamble: Injected into the expert's LLM prompt to
            constrain its persona and behavior.
        anchor_phrases: Example user utterances that should route here.
            Used by the semantic router for embedding alignment.
        max_iterations: Maximum Plan-and-Solve loop iterations for this expert.
    """

    name: str
    display_name: str
    description: str
    categories: tuple[ToolCategory, ...]
    system_prompt_preamble: str
    anchor_phrases: tuple[str, ...] = ()
    max_iterations: int = 3


# =============================================================================
# AGENT PROFILE REGISTRY
# =============================================================================

AGENT_PROFILES: tuple[AgentProfile, ...] = (
    AgentProfile(
        name="email_expert",
        display_name="📧 Email Expert",
        description="Handles reading, composing, and managing emails via IMAP/SMTP.",
        categories=(ToolCategory.COMMUNICATION,),
        system_prompt_preamble=(
            "You are the Email Expert of Amadeus AI. You specialize in reading, "
            "composing, replying, and managing emails. Only use email-related tools. "
            "Be concise and professional."
        ),
        anchor_phrases=(
            "check my inbox", "read my emails", "send an email",
            "compose a message", "unread emails", "reply to email",
            "forward this email", "email summary", "any new messages",
            "send email to", "check my email", "draft a reply",
        ),
        max_iterations=3,
    ),
    AgentProfile(
        name="task_expert",
        display_name="📅 Task & Productivity Expert",
        description=(
            "Manages tasks, notes, reminders, and pomodoro timers. "
            "Handles personal productivity workflows."
        ),
        categories=(ToolCategory.TASK_MANAGER, ToolCategory.PRODUCTIVITY),
        system_prompt_preamble=(
            "You are the Task & Productivity Expert of Amadeus AI. You manage "
            "tasks, notes, reminders, pomodoro timers, and personal productivity. "
            "Be organized and action-oriented."
        ),
        anchor_phrases=(
            "add a task", "list my tasks", "create a reminder",
            "show my notes", "start pomodoro", "set a timer",
            "complete task", "what are my todos", "remind me",
            "take a note", "schedule future task", "remember that",
        ),
        max_iterations=3,
    ),
    AgentProfile(
        name="system_expert",
        display_name="💻 System & Shell Expert",
        description=(
            "Controls system operations: volume, brightness, screenshots, "
            "running terminal commands, opening/closing applications, "
            "and managing files on the filesystem."
        ),
        categories=(
            ToolCategory.OS_CONTROL,
            ToolCategory.APP_CONTROL,
            ToolCategory.FILE_SYSTEM,
        ),
        system_prompt_preamble=(
            "You are the System Expert of Amadeus AI. You control the operating "
            "system: volume, brightness, screenshots, applications, terminal "
            "commands, and file management. Be precise and cautious with "
            "destructive operations."
        ),
        anchor_phrases=(
            "set volume", "take a screenshot", "open chrome",
            "close notepad", "find file", "create folder",
            "run command", "increase brightness", "list open apps",
            "search files", "delete file", "move file",
            "copy file", "what programs are running",
        ),
        max_iterations=4,
    ),
    AgentProfile(
        name="research_expert",
        display_name="🔍 Web Research Expert",
        description=(
            "Performs web searches, Wikipedia lookups, news retrieval, "
            "weather queries, calculations, and fetching webpage content."
        ),
        categories=(
            ToolCategory.WEB_RESEARCH,
            ToolCategory.WEATHER,
            ToolCategory.CALCULATION,
        ),
        system_prompt_preamble=(
            "You are the Research Expert of Amadeus AI. You handle web searches, "
            "Wikipedia lookups, news, weather, calculations, and webpage fetching. "
            "Provide accurate, well-sourced information."
        ),
        anchor_phrases=(
            "search the web", "what is the weather", "latest news",
            "who is", "calculate", "wikipedia", "google this",
            "look up", "search for", "headlines today",
            "temperature", "web search", "fetch this webpage",
        ),
        max_iterations=3,
    ),
    AgentProfile(
        name="generalist",
        display_name="🧠 Generalist",
        description=(
            "Fallback expert for conversational queries, chit-chat, "
            "complex reasoning, content generation, and anything that "
            "doesn't match a specialized expert."
        ),
        categories=(),  # Empty — uses ALL tools as fallback
        system_prompt_preamble=(
            "You are Amadeus AI, a versatile personal assistant. Handle this "
            "request conversationally. If the task is complex, break it down "
            "step by step."
        ),
        anchor_phrases=(
            "hello", "who are you", "tell me a joke",
            "write an essay", "explain this concept",
            "what can you do", "help me with",
        ),
        max_iterations=5,
    ),
)

# Build a lookup: ToolCategory -> AgentProfile
_CATEGORY_TO_PROFILE: dict[ToolCategory, AgentProfile] = {}
for _profile in AGENT_PROFILES:
    for _cat in _profile.categories:
        _CATEGORY_TO_PROFILE[_cat] = _profile


def get_profile_for_category(category: ToolCategory) -> AgentProfile:
    """Return the AgentProfile that owns the given ToolCategory.

    Falls back to the generalist if no specialized expert owns it.
    """
    return _CATEGORY_TO_PROFILE.get(category, AGENT_PROFILES[-1])  # last = generalist


def get_profile_by_name(name: str) -> AgentProfile | None:
    """Look up an AgentProfile by its unique name."""
    for profile in AGENT_PROFILES:
        if profile.name == name:
            return profile
    return None


def get_all_profiles() -> tuple[AgentProfile, ...]:
    """Return all registered agent profiles."""
    return AGENT_PROFILES
