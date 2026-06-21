"""
Agent Profiles for the Agentic Mixture-of-Experts (MoE) architecture.

Each AgentProfile defines a specialized sub-agent that the Supervisor Router
can activate. By constraining each expert to a small subset of tools and a
focused system prompt, we dramatically reduce the LLM context window and
improve zero-shot accuracy.

The 11 Native Experts (per CLAUDE.md architecture mandate):
    os_expert, monitor_expert, filesystem_expert, developer_expert,
    task_expert, memory_expert, finance_expert, news_expert,
    research_expert, math_expert, email_expert
plus the `generalist` fallback for pure conversational queries.

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
# AGENT PROFILE REGISTRY — the 11 Native Experts + generalist fallback
# =============================================================================

AGENT_PROFILES: tuple[AgentProfile, ...] = (
    AgentProfile(
        name="os_expert",
        display_name="💻 OS Expert",
        description=(
            "Controls the host operating system: taking screenshots, opening "
            "and launching applications, closing and terminating programs, "
            "and listing the currently running applications."
        ),
        categories=(ToolCategory.OS_CONTROL, ToolCategory.APP_CONTROL),
        system_prompt_preamble=(
            "You are the OS Expert of Amadeus AI. You control the host system: "
            "screenshots, opening/closing applications, and listing running "
            "programs. Be precise and cautious with anything that terminates "
            "a program."
        ),
        anchor_phrases=(
            "take a screenshot", "open chrome", "launch firefox",
            "close spotify", "kill that process", "terminate the app",
            "what programs are running", "list open apps",
            "start the calculator", "open my text editor",
        ),
        max_iterations=3,
    ),
    AgentProfile(
        name="monitor_expert",
        display_name="📊 System Monitor Expert",
        description=(
            "Monitors host system health read-only: CPU, memory, disk, and "
            "battery levels, network connectivity, temperature sensors, "
            "uptime, running process stats, and system alerts."
        ),
        categories=(ToolCategory.MONITORING,),
        system_prompt_preamble=(
            "You are the System Monitor Expert of Amadeus AI. You report on "
            "system health: CPU, memory, disk, battery, network, temperatures, "
            "and uptime. You are strictly read-only — report exact numbers "
            "from your tools and flag anything that looks unhealthy."
        ),
        anchor_phrases=(
            "system status", "cpu usage", "memory usage", "ram usage",
            "battery level", "disk space", "how long has the pc been on",
            "is my internet working", "network info", "system temperature",
            "any system alerts", "is the system healthy", "system report",
        ),
        max_iterations=2,
    ),
    AgentProfile(
        name="filesystem_expert",
        display_name="📁 Filesystem Expert",
        description=(
            "Performs local file operations: searching for files, copying, "
            "moving, deleting files, creating folders, and reading or writing "
            "files in the agent workspace."
        ),
        categories=(ToolCategory.FILE_SYSTEM,),
        system_prompt_preamble=(
            "You are the Filesystem Expert of Amadeus AI. You search, copy, "
            "move, and delete files and create folders. Destructive operations "
            "(delete, move, overwrite) are gated — always double-check paths "
            "before acting."
        ),
        anchor_phrases=(
            "find file report.pdf", "search for a file", "where is my resume",
            "copy this file to desktop", "move document to downloads",
            "delete the old backup", "create a folder called projects",
            "make a new directory", "list the files in that folder",
            "read this text file", "write this to a file",
        ),
        max_iterations=4,
    ),
    AgentProfile(
        name="developer_expert",
        display_name="🛠️ Developer Expert",
        description=(
            "Writes and executes Python code in a sandbox, runs terminal "
            "commands, and semantically searches the local code workspace."
        ),
        categories=(ToolCategory.DEVELOPER,),
        system_prompt_preamble=(
            "You are the Developer Expert of Amadeus AI. You write and run "
            "Python scripts in a secure sandbox (standard library only), run "
            "terminal commands, and search the local code workspace. Write "
            "self-contained, correct code and report exact output."
        ),
        anchor_phrases=(
            "write and run a python script", "execute this code",
            "run python code to compute fibonacci", "run a terminal command",
            "ping google.com", "what is my ip address",
            "search my codebase for", "where is this function defined",
            "find the config in my projects", "code this up and run it",
        ),
        max_iterations=4,
    ),
    AgentProfile(
        name="task_expert",
        display_name="📅 Task & Notes Expert",
        description=(
            "Manages tasks, notes, reminders, and pomodoro timers. Handles "
            "personal productivity workflows strictly sequentially."
        ),
        categories=(ToolCategory.TASK_MANAGER,),
        system_prompt_preamble=(
            "You are the Task & Notes Expert of Amadeus AI. You manage tasks, "
            "notes, reminders, and pomodoro timers. Execute operations "
            "strictly one at a time, in order. Be organized and action-oriented."
        ),
        anchor_phrases=(
            "add a task", "list my tasks", "create a reminder",
            "show my notes", "take a note", "start pomodoro",
            "set a timer for 5 minutes", "complete task 3",
            "what are my todos", "remind me at 5pm",
        ),
        max_iterations=3,
    ),
    AgentProfile(
        name="memory_expert",
        display_name="🧠 Memory & Goals Expert",
        description=(
            "Manages the assistant's long-term core memory about the user, "
            "personal goals (creating, updating, decomposing, tracking), and "
            "scheduling future agent tasks."
        ),
        categories=(ToolCategory.PRODUCTIVITY,),
        system_prompt_preamble=(
            "You are the Memory & Goals Expert of Amadeus AI. You store and "
            "recall long-term facts about the user, manage their goals, and "
            "schedule future tasks for the agent. Store facts exactly as the "
            "user states them, and never invent memories."
        ),
        anchor_phrases=(
            "remember that my favorite color is blue", "remember this about me",
            "what do you know about me", "forget that fact",
            "create a goal", "update my goal", "show my active goals",
            "break this goal into steps", "schedule this for later",
            "schedule a task for tomorrow",
        ),
        max_iterations=3,
    ),
    AgentProfile(
        name="finance_expert",
        display_name="📈 Finance Expert",
        description=(
            "Provides stock market quotes and cryptocurrency prices: share "
            "prices, day changes, and crypto rates in any currency."
        ),
        categories=(ToolCategory.FINANCE,),
        system_prompt_preamble=(
            "You are the Finance Expert of Amadeus AI. You fetch live stock "
            "quotes and cryptocurrency prices. Report numbers exactly as "
            "returned by your tools — never invent or extrapolate prices."
        ),
        anchor_phrases=(
            "stock price of apple", "how is tesla stock doing",
            "reliance share price", "what is the nifty at",
            "bitcoin price", "how much is ethereum",
            "btc in inr", "crypto prices today",
            "ethereum price in inr", "bitcoin price in dollars",
            "did the market go up today", "check my stock",
        ),
        max_iterations=3,
    ),
    AgentProfile(
        name="news_expert",
        display_name="📰 News Expert",
        description=(
            "Fetches and summarizes news headlines by category and country: "
            "technology, business, sports, health, science, entertainment."
        ),
        categories=(ToolCategory.NEWS,),
        system_prompt_preamble=(
            "You are the News Expert of Amadeus AI. You fetch top headlines "
            "by category and country and summarize them concisely with their "
            "sources. Never fabricate headlines."
        ),
        anchor_phrases=(
            "latest news", "headlines today", "tech news",
            "sports news today", "business headlines",
            "what's happening in the world", "breaking news",
            "news about india", "current events", "show me today's news",
        ),
        max_iterations=2,
    ),
    AgentProfile(
        name="research_expert",
        display_name="🔍 Research Expert",
        description=(
            "Performs web searches, Wikipedia lookups, weather queries, and "
            "fetches webpage content for reading and summarization."
        ),
        categories=(ToolCategory.WEB_RESEARCH, ToolCategory.WEATHER),
        system_prompt_preamble=(
            "You are the Research Expert of Amadeus AI. You handle web "
            "searches, Wikipedia lookups, weather queries, and webpage "
            "fetching. Provide accurate, well-sourced information and cite "
            "where it came from."
        ),
        anchor_phrases=(
            "search the web for", "look this up online", "google this",
            "who is albert einstein", "what is quantum computing",
            "wikipedia machine learning", "fetch this webpage",
            "read this url", "what is the weather in mumbai",
            "is it raining", "temperature today", "research this topic",
        ),
        max_iterations=3,
    ),
    AgentProfile(
        name="math_expert",
        display_name="🧮 Math Expert",
        description=(
            "Performs calculations, evaluates math expressions, converts "
            "currencies with live exchange rates, and converts units "
            "(temperature, length)."
        ),
        categories=(ToolCategory.CALCULATION,),
        system_prompt_preamble=(
            "You are the Math Expert of Amadeus AI. You evaluate math "
            "expressions, convert currencies with live rates, and convert "
            "units. Translate natural language into exact tool arguments "
            "(e.g. '15% of 5000' → expression '5000 * 0.15')."
        ),
        anchor_phrases=(
            "calculate 15 percent of 5000", "what is 2 plus 2",
            "square root of 144", "solve 500 divided by 4",
            "convert 100 usd to inr", "how much is 50 euros in dollars",
            "convert 5 km to miles", "100 celsius to fahrenheit",
            "exchange rate usd to inr", "what is log of 100",
        ),
        max_iterations=2,
    ),
    AgentProfile(
        name="email_expert",
        display_name="📧 Email Expert",
        description="Handles reading, composing, and managing emails via IMAP/SMTP.",
        categories=(ToolCategory.COMMUNICATION,),
        system_prompt_preamble=(
            "You are the Email Expert of Amadeus AI. You specialize in reading, "
            "composing, replying, and managing emails via IMAP/SMTP. Only use "
            "email-related tools. Be concise and professional, and never send "
            "an email the user did not ask for."
        ),
        anchor_phrases=(
            "check my inbox", "read my emails", "send an email",
            "compose a message", "unread emails", "reply to email",
            "forward this email", "email summary", "any new messages",
            "send email to", "check my email", "draft a reply",
        ),
        max_iterations=3,
    ),
    # NOTE: generalist must remain LAST — AGENT_PROFILES[-1] is the fallback.
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
