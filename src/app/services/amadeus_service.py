"""
Amadeus Service - Main AI Assistant Orchestrator.

This service is migrated from amadeus.py and preserves the ML classifier
approach for tool selection to save Gemini API quota.

Architecture:
- Public API: handle_command, get_response
- Internal Logic: _process_command_internal, _select_tools
- Infrastructure: tool registry, conversation manager, voice services
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from src.infra.cache.cache_service import CacheService

    class IConversationRepository:
        """Protocol for conversation repository (typing only)."""

        async def add_message(
            self, session_id: str, role: str, content: str, tool_used: str | None = None
        ) -> None: ...
        async def get_recent_context(
            self, session_id: str, limit: int = 20
        ) -> list[dict[str, Any]]: ...
        async def clear_session(self, session_id: str) -> None: ...


import joblib
import numpy as np
from google import genai
from google.genai import types

from src.app.services.tool_registry import ToolRegistry
from src.core.config import Settings, get_settings
from src.core.domain.models import PermissionProfile
from src.infra.memory_service import QdrantMemoryService
from src.infra.messaging.telegram_adapter import TelegramAdapter
from src.infra.messaging.whatsapp_adapter import WhatsAppAdapter
from src.infra.tools.base import ToolExecutor


logger = logging.getLogger(__name__)


# =============================================================================
# CONVERSATION MANAGEMENT
# =============================================================================


@dataclass
class ConversationMessage:
    """Structured conversation message."""

    role: str  # 'user' or 'assistant'
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    tool_used: str | None = None
    metadata: dict = field(default_factory=dict)


class ConversationManager:
    """
    Manages conversation history with UNIFIED storage.

    When a repository is provided, ALL operations go through the database.
    The in-memory cache is only for performance optimization within a session,
    and is always synchronized with the database.

    This solves the "dual memory split" problem where in-memory and DB
    would get out of sync on server restart.
    """

    def __init__(
        self,
        session_id: str,
        repo: "IConversationRepository | None" = None,
        max_context: int = 20,
    ):
        self.session_id = session_id
        self.repo = repo
        self.max_context = max_context

        # In-memory cache (synchronized with DB)
        self._cache: list[ConversationMessage] = []
        self._cache_loaded = False

    async def add(
        self, role: str, content: str, tool_used: str | None = None, **metadata: Any
    ) -> None:
        """Add a message - goes to DB first if repo available."""
        msg = ConversationMessage(
            role=role,
            content=content,
            tool_used=tool_used,
            metadata=metadata,
        )

        # Persist to database FIRST (source of truth)
        if self.repo:
            await self.repo.add_message(
                session_id=self.session_id,
                role=role,
                content=content,
                tool_used=tool_used,
            )

        # Then update cache
        self._cache.append(msg)
        self._trim_cache()

    async def load_from_db(self) -> None:
        """Load conversation history from database on startup."""
        if not self.repo or self._cache_loaded:
            return

        try:
            messages = await self.repo.get_recent_context(
                session_id=self.session_id,
                limit=self.max_context,
            )

            self._cache = [
                ConversationMessage(
                    role=m["role"],
                    content=m["content"],
                    tool_used=m.get("tool_used"),
                    timestamp=datetime.fromisoformat(m["timestamp"])
                    if m.get("timestamp")
                    else datetime.now(),
                )
                for m in messages
            ]
            self._cache_loaded = True
            logger.info(
                f"Loaded {len(self._cache)} messages from DB for session {self.session_id[:8]}..."
            )
        except Exception as e:
            logger.exception(f"Failed to load conversation history: {e}")

    def _trim_cache(self) -> None:
        """Keep cache within limits — always preserves the most recent messages."""
        if len(self._cache) > self.max_context:
            self._cache = self._cache[-self.max_context :]

    def get_messages(self) -> list[ConversationMessage]:
        """Get cached messages."""
        return self._cache

    def get_formatted_history(self, last_n: int = 5) -> str:
        """Get formatted conversation history for the AI prompt."""
        recent = self._cache[-last_n:] if len(self._cache) > last_n else self._cache
        formatted = []
        for msg in recent:
            prefix = "User" if msg.role == "user" else "Amadeus"
            tool_info = f" [used: {msg.tool_used}]" if msg.tool_used else ""
            formatted.append(f"{prefix}{tool_info}: {msg.content}")
        return "\n".join(formatted)

    def get_context_summary(self) -> str:
        """Generate a brief summary of the conversation context."""
        if not self._cache:
            return "No prior conversation."

        tools_used = [m.tool_used for m in self._cache if m.tool_used]
        topics = set()
        for m in self._cache[-5:]:
            words = m.content.lower().split()
            for kw in ["weather", "news", "task", "reminder", "note", "file", "time", "system"]:
                if kw in words:
                    topics.add(kw)

        return f"Recent topics: {', '.join(topics) or 'general'}. Tools used: {', '.join(set(tools_used[-3:])) or 'none'}."

    async def clear(self) -> None:
        """Clear conversation history from both cache and DB."""
        if self.repo:
            await self.repo.clear_session(self.session_id)
        self._cache.clear()
        self._cache_loaded = False


# =============================================================================
# AMADEUS SERVICE
# =============================================================================


class AmadeusService:
    """
    Main AI Assistant Orchestrator Service.

    Preserves the ML classifier approach from amadeus.py for efficient
    tool selection without consuming Gemini API quota.

    Supports optional persistent conversation storage via IConversationRepository.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        tool_registry: ToolRegistry | None = None,
        conversation_repo: "IConversationRepository | None" = None,
        session_id: str | None = None,
        debug_mode: bool = False,
        cache_service: "CacheService | None" = None,
        auto_start_orchestrator: bool = True,
        llm_router: Any = None,
    ):
        self.settings = settings or get_settings()
        self.debug_mode = debug_mode
        self.cache_service = cache_service

        if llm_router:
            self.llm_router = llm_router
        else:
            try:
                from src.container import get_llm_router
                self.llm_router = get_llm_router()
            except Exception:
                self.llm_router = None

        self.session_id = session_id or str(uuid.uuid4())

        # UNIFIED conversation manager (uses DB as source of truth)
        self.conversation_manager = ConversationManager(
            session_id=self.session_id,
            repo=conversation_repo,
        )

        self.tool_executor = ToolExecutor()
        self.tool_registry = tool_registry or ToolRegistry()

        # Long-term semantic memory (Qdrant + Gemini embeddings)
        self.memory_service = QdrantMemoryService(settings=self.settings)
        if self.memory_service.is_enabled:
            logger.info(
                "Long-term memory ENABLED — ChromaDB ready (%d stored memories)",
                self.memory_service.memory_count,
            )
        else:
            logger.info("Long-term memory DISABLED — operating with session-only context")

        # Initialize components
        self._load_api_keys()
        self._load_tool_classifier()
        self._register_all_tools()

        # Build identity prompt
        self.identity_prompt = self._build_identity_prompt()

        # Initialize Agent Orchestrator (holds the background worker loop)
        from src.app.services.agent_loop import AgentOrchestrator

        # Build an async llm_generate closure that wraps the synchronous
        # Gemini SDK call in run_in_executor so it never blocks the event loop.
        llm_generate = None
        if hasattr(self, "client") and self.client:

            async def _generate(prompt: str) -> str:
                loop = asyncio.get_running_loop()
                assert self.client is not None
                response = await loop.run_in_executor(
                    None,
                    lambda: self.client.models.generate_content(  # type: ignore[union-attr]
                        model=self.model_name,
                        contents=prompt,
                    ),
                )
                return str(response.text) if hasattr(response, "text") else str(response)

            llm_generate = _generate

        self.orchestrator = AgentOrchestrator(
            tool_registry=self.tool_registry,
            tool_executor=self.tool_executor,
            llm_generate=llm_generate,
            auto_start=auto_start_orchestrator,
        )

        logger.info(
            f"AmadeusService initialized with {len(self.tool_registry)} tools, session={self.session_id[:8]}..."
        )

    async def initialize(self) -> None:
        """Async initialization - initialize memory service and load conversation history from DB."""
        await self.memory_service.initialize()
        await self.conversation_manager.load_from_db()

    # =========================================================================
    # INITIALIZATION
    # =========================================================================

    def _load_api_keys(self) -> None:
        """Load and configure API keys."""
        if not self.settings.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not found - AI features will be limited")
            self.client = None
            return

        self.client = genai.Client(api_key=self.settings.GEMINI_API_KEY)
        self.model_name = self.settings.GEMINI_MODEL
        logger.info(f"Gemini API configured with model: {self.model_name}")

    def _load_tool_classifier(self) -> None:
        """
        Load TF-IDF vectorizer and SVM classifier for smart tool selection.

        This is the key quota-saving feature: predict relevant tools locally
        instead of sending all tools to Gemini with every request.
        """
        try:
            vectorizer_path = "Model/tfidf_vectorizer.joblib"
            classifier_path = "Model/svm_classifier.joblib"

            if Path(vectorizer_path).exists() and Path(classifier_path).exists():
                self.vectorizer = joblib.load(vectorizer_path)
                self.classifier = joblib.load(classifier_path)
                self.classifier_enabled = True
                logger.info("Tool classifier models loaded. Smart tool selection ENABLED.")
            else:
                logger.warning("Tool classifier models not found. Using all-tools mode.")
                self.classifier_enabled = False
        except Exception as e:
            logger.exception(f"Failed to load tool classifier: {e}")
            self.classifier_enabled = False

    def _register_all_tools(self) -> None:
        """Register all tools from the tool modules."""
        # Import and register tools from each module
        try:
            from src.infra.tools.agent_tools import get_agent_tools
            from src.infra.tools.filesystem_tools import build_filesystem_tools
            from src.infra.tools.info_tools import get_info_tools
            from src.infra.tools.monitor_tools import get_monitor_tools
            from src.infra.tools.productivity_tools import get_productivity_tools
            from src.infra.tools.system_tools import get_system_tools

            for tool in get_info_tools():
                self.tool_registry.register(tool)
            for tool in get_system_tools():
                self.tool_registry.register(tool)
            for tool in get_monitor_tools():
                self.tool_registry.register(tool)
            for tool in get_productivity_tools():
                self.tool_registry.register(tool)
            for tool in get_agent_tools():
                self.tool_registry.register(tool)
            for tool in build_filesystem_tools():
                self.tool_registry.register(tool)

            logger.info(f"Registered {len(self.tool_registry)} tools from modules")
        except Exception as e:
            logger.exception(f"Error registering tools: {e}")

    def _build_identity_prompt(self) -> str:
        """Build the identity prompt for the AI."""
        return f"""You are {self.settings.ASSISTANT_NAME}, an intelligent AI assistant.

Personality: {self.settings.ASSISTANT_PERSONALITY}
Current time: {{current_time}}
Current Session ID: {{session_id}}
Conversation context: {{context_summary}}

Guidelines:
- Be concise, natural, and contextually aware
- Don't introduce yourself unless asked
- When using tools, explain what you're doing briefly
- If a task fails, suggest alternatives
- Adapt tone based on task urgency
- Use the schedule_future_task tool to remind yourself to follow up proactively"""

    # =========================================================================
    # TOOL SELECTION (ML CLASSIFIER)
    # =========================================================================

    def _predict_relevant_tools(self, query: str, top_k: int = 3) -> list[str]:
        """
        Predict relevant tools using the loaded SVM model.

        This is the quota-saving magic: instead of sending all 45+ tools
        to Gemini, we predict which 3 tools are most likely relevant.

        Args:
            query: User's input text
            top_k: Number of top tools to return

        Returns:
            List of tool names, or ["conversational"] if no tool needed
        """
        if not self.classifier_enabled:
            return self.tool_registry.list_names()

        try:
            # Vectorize user query
            x_vec = self.vectorizer.transform([query])

            # Get scores from SVM
            scores = self.classifier.decision_function(x_vec)[0]
            classes = self.classifier.classes_

            # Sort by confidence
            top_indices = np.argsort(scores)[::-1]
            best_tool = classes[top_indices[0]]

            # Check for conversational intent
            if best_tool == "conversational":
                logger.info("Classifier predicted 'conversational' - skipping tools")
                return ["conversational"]

            # Get top K tools
            top_tools = classes[top_indices[:top_k]]

            # Filter to tools that exist in registry
            relevant = [t for t in top_tools if t in self.tool_registry]

            if not relevant:
                logger.warning(f"Predicted tools {top_tools} not in registry. Fallback to all.")
                return self.tool_registry.list_names()

            logger.info(f"Smart Tool Selection: {relevant} (best: {best_tool})")
            return relevant

        except Exception as e:
            logger.exception(f"Error predicting tools: {e}. Fallback to all.")
            return self.tool_registry.list_names()

    # =========================================================================
    # COMMAND PROCESSING
    # =========================================================================

    async def handle_command(
        self,
        user_input: str,
        source: str = "text",
        request_id: str | None = None,
        permission_profile: PermissionProfile = PermissionProfile.SYSTEM_FULL,
    ) -> str:
        """
        Main entry point for processing user commands.

        Args:
            user_input: The user's input text
            source: Source of input (voice, text, api)
            request_id: Optional request ID for tracing
            permission_profile: Security clearance for this execution

        Returns:
            Assistant's response as string
        """
        if not user_input.strip():
            return "I didn't catch that. Could you repeat?"

        try:
            # Add user message (ConversationManager handles both cache AND DB)
            await self.conversation_manager.add("user", user_input)

            # Store user message in long-term semantic memory
            await self.memory_service.store(self.session_id, "user", user_input)

            # Check if this is a multi-step query that needs the agent
            if self._is_multi_step_query(user_input):
                response, tools_used = await self._process_with_agent(
                    user_input, permission_profile=permission_profile
                )
                tool_used = ", ".join(tools_used) if tools_used else None
            else:
                # Single-step processing
                response, tool_used = await self._process_command_internal(
                    user_input,
                    permission_profile=permission_profile,
                )

            # Add assistant response (unified - goes to both cache and DB)
            await self.conversation_manager.add("assistant", response, tool_used=tool_used)

            # Store assistant response in long-term semantic memory
            await self.memory_service.store(self.session_id, "assistant", response)

            return response

        except Exception as e:
            from src.app.services.agent_loop import QueueFullError

            if isinstance(e, QueueFullError):
                raise  # Let backpressure errors propagate up to the API layer

            logger.error(f"Error handling command: {e}", exc_info=True)
            if self.debug_mode or getattr(self.settings, "ALLOW_DEBUG_RESPONSES", False):
                return f"I encountered an error ({type(e).__name__}). Check the server logs for details."
            return "I encountered an unexpected error. Please try again."

    def _is_multi_step_query(self, user_input: str) -> bool:
        """
        Detect if a query requires multi-step reasoning.

        Multi-step indicators:
        - Multiple action words (and, then, also)
        - Multiple distinct intents
        """
        lower = user_input.lower()

        # Conjunctions that indicate multiple actions
        multi_indicators = [" and ", " then ", " also ", " plus ", " as well as "]
        has_conjunction = any(ind in lower for ind in multi_indicators)

        # Check for multiple distinct intents
        intent_keywords = [
            ["time", "date", "day"],
            ["weather", "temperature"],
            ["joke", "funny"],
            ["task", "todo"],
            ["note"],
            ["reminder"],
            ["system", "cpu", "memory"],
            ["news"],
            ["battery"],
        ]

        intent_count = sum(1 for keywords in intent_keywords if any(kw in lower for kw in keywords))

        return has_conjunction and intent_count >= 2

    async def _process_with_agent(
        self,
        user_input: str,
        permission_profile: PermissionProfile = PermissionProfile.SYSTEM_FULL,
    ) -> tuple[str, list[str]]:
        """
        Process a multi-step query using the Agent Orchestrator.
        """
        context = self.conversation_manager.get_context_summary()

        # Submit task to the background Orchestrator queue
        result = await self.orchestrator.execute(
            task=user_input,
            context=context,
            permission_profile=permission_profile,
        )

        if result.success:
            return (result.final_answer, result.tools_used)
        return (result.error or "I couldn't complete that task.", [])

    async def handle_background_event(self, event_prompt: str) -> None:
        """
        Handle a background event prompt silently. Process proactive agent logic.
        """
        try:
            # We don't add the background prompt to the user history
            # Just push it to the agent directly.
            _response, tools_used = await self._process_with_agent(event_prompt)
            # The agent executes tools. If it uses schedule_future_task or send_outbound_message,
            # they are executed within _process_with_agent.
            logger.info(f"Background event processed. Tools used: {tools_used}")
        except Exception as e:
            logger.exception(f"Error handling background event: {e}")

    async def _process_command_internal(
        self,
        user_input: str,
        permission_profile: PermissionProfile = PermissionProfile.SYSTEM_FULL,
    ) -> tuple[str, str | None]:
        """
        Internal command processing — LOCAL-FIRST architecture.

        Flow:
        1. SVM classifier predicts which tool (or "conversational") — 100% local
        2. If conversational → Groq/LlamaCpp via LLMRouter (no Gemini used)
        3. If tool needed:
           a. Try to execute the tool directly using keyword-extracted args (local)
           b. Use LlamaCpp/Groq to compose a natural language response (local)
        4. Only fall back to Gemini if no local model available AND Gemini is configured

        Returns:
            Tuple of (response_text, tool_used_name or None)
        """
        # Step 1: Predict relevant tools via local SVM classifier
        relevant_tools = self._predict_relevant_tools(user_input)

        # Step 2: Conversational — route to LLMRouter (Groq/LlamaCpp), never Gemini
        if relevant_tools == ["conversational"]:
            response = await self._generate_conversational_response(user_input)
            return (response, None)

        # Step 3: Tool execution — try local-first approach
        tool_name = relevant_tools[0]  # Best prediction from SVM
        tool = self.tool_registry.get(tool_name)

        if tool:
            # Extract args from user input using simple keyword parsing
            args = self._extract_args_for_tool(tool_name, user_input)
            result = await self.tool_executor.execute(
                tool, args, permission_profile=permission_profile
            )

            if result.success:
                # Use LLMRouter (Llama/Groq) to compose a natural response
                response_text = await self._compose_tool_response_locally(
                    user_input, tool_name, str(result.result)
                )
                return (response_text, tool_name)
            else:
                # Tool failed — tell user clearly
                return (
                    f"I tried to use {tool_name} but encountered an issue: {result.error_message}",
                    tool_name,
                )

        # Step 4: Tool not in registry — fall back to Gemini if available
        if getattr(self, "client", None):
            return await self._process_with_gemini(user_input, relevant_tools, permission_profile)

        return (
            "I couldn't find the right tool for that. Try rephrasing your request.",
            None,
        )

    def _extract_args_for_tool(self, tool_name: str, user_input: str) -> dict:
        """
        Extract tool arguments from user input using simple keyword/pattern matching.
        This avoids any LLM call for argument extraction — 100% local & instant.
        """
        text = user_input.strip()
        lower = text.lower()

        # Generic patterns for common tools
        if tool_name == "open_program":
            # "open VLC", "launch Chrome", "start Discord"
            for kw in ["open ", "launch ", "start ", "run "]:
                if kw in lower:
                    app = text[lower.index(kw) + len(kw):].strip()
                    return {"app_name": app}
            return {"app_name": text}

        if tool_name == "terminate_program":
            for kw in ["close ", "kill ", "stop ", "terminate ", "end "]:
                if kw in lower:
                    app = text[lower.index(kw) + len(kw):].strip()
                    return {"process_name": app}
            return {"process_name": text}

        if tool_name == "search_file":
            for kw in ["find ", "locate ", "where is ", "search for "]:
                if kw in lower:
                    return {"file_name": text[lower.index(kw) + len(kw):].strip()}
            return {"file_name": text}

        if tool_name in ("web_search", "wikipedia_search"):
            for kw in ["search for ", "search ", "look up ", "google ", "find info about ", "what is ", "who is ", "tell me about "]:
                if kw in lower:
                    return {"query": text[lower.index(kw) + len(kw):].strip()}
            return {"query": text}

        if tool_name == "get_weather":
            return {"location": "current location"}

        if tool_name == "get_news":
            return {"topic": text}

        if tool_name == "calculate":
            for kw in ["calculate ", "compute ", "what is ", "evaluate "]:
                if kw in lower:
                    return {"expression": text[lower.index(kw) + len(kw):].strip()}
            return {"expression": text}

        if tool_name == "create_note":
            for kw in ["note ", "note: ", "save note "]:
                if kw in lower:
                    return {"content": text[lower.index(kw) + len(kw):].strip()}
            return {"content": text}

        if tool_name == "add_reminder":
            return {"reminder_text": text, "time_str": ""}

        if tool_name == "set_timer":
            import re
            minutes = re.search(r"(\d+)\s*minute", lower)
            seconds = re.search(r"(\d+)\s*second", lower)
            if minutes:
                return {"duration_seconds": int(minutes.group(1)) * 60}
            if seconds:
                return {"duration_seconds": int(seconds.group(1))}
            return {"duration_seconds": 300}

        if tool_name == "convert_temperature":
            return {"expression": text}

        if tool_name == "convert_length":
            return {"expression": text}

        # Default: pass full user input as a generic query param
        return {"query": text}

    async def _compose_tool_response_locally(
        self, user_input: str, tool_name: str, tool_result: str
    ) -> str:
        """
        Use LLMRouter (Llama-cpp first, then Groq) to compose a friendly response
        incorporating the tool result. No Gemini call needed.
        """
        prompt = (
            f"The user asked: '{user_input}'\n"
            f"You ran the tool '{tool_name}' and got this result:\n{tool_result}\n\n"
            f"Compose a brief, natural, conversational response to the user based on this result. "
            f"Be concise — 1-2 sentences max."
        )
        try:
            if hasattr(self, "llm_router") and self.llm_router:
                text, provider = await self.llm_router.generate(prompt=prompt, complexity="normal")
                logger.info("Tool response composed by router (provider=%s)", provider)
                return text
        except Exception as e:
            logger.warning("LLMRouter failed for tool response composition: %s", e)

        # Ultimate fallback: return the raw tool result directly
        return tool_result

    async def _process_with_gemini(
        self,
        user_input: str,
        relevant_tools: list[str],
        permission_profile: PermissionProfile = PermissionProfile.SYSTEM_FULL,
    ) -> tuple[str, str | None]:
        """
        Gemini-backed processing — used ONLY as a last resort when the tool
        is not in the registry or local processing fails.
        """
        current_time = datetime.now().strftime("%I:%M %p on %A, %B %d")
        context_summary = self.conversation_manager.get_context_summary()

        long_term_memories = await self.memory_service.retrieve(user_input, top_k=5)
        memory_context = self.memory_service.format_for_prompt(long_term_memories)

        system_prompt = self.identity_prompt.format(
            current_time=current_time,
            session_id=self.session_id,
            context_summary=context_summary,
        )
        if memory_context:
            system_prompt = f"{system_prompt}\n\n{memory_context}"

        tools_config = self.tool_registry.build_gemini_tools(relevant_tools)

        if self.cache_service:
            cached_llm = await self.cache_service.get_llm(user_input, "gemini")
            if cached_llm:
                logger.info("LLM cache hit (%d chars)", len(user_input))
                return (cached_llm, None)

        try:
            config = types.GenerateContentConfig(
                tools=tools_config if tools_config else None,
            )
            assert self.client is not None
            gemini_response = self.client.models.generate_content(
                model=self.model_name,
                contents=system_prompt + "\n\n" + user_input,
                config=config,
            )

            if gemini_response.function_calls:
                fc = gemini_response.function_calls[0]
                tool_name = fc.name or "unknown"
                result = await self._execute_function_call(
                    fc, permission_profile=permission_profile
                )
                final_response = await self._generate_response_with_result(
                    user_input, tool_name, result
                )
                return (final_response, tool_name)

            direct_response = (
                str(gemini_response.text)
                if hasattr(gemini_response, "text") and gemini_response.text
                else str(gemini_response)
            )

            try:
                from src.infra.metrics import amadeus_llm_calls_total
                amadeus_llm_calls_total.labels(provider="gemini").inc()
            except Exception:
                pass

            if self.cache_service:
                await self.cache_service.set_llm(user_input, direct_response, "gemini")
            return (direct_response, None)

        except Exception as e:
            logger.exception("Gemini API error: %s", repr(e))
            return (f"I had trouble processing that: {e}", None)


    async def _process_without_gemini(
        self,
        user_input: str,
        permission_profile: PermissionProfile = PermissionProfile.SYSTEM_FULL,
    ) -> tuple[str, str | None]:
        """Fallback processing when Gemini is not available."""
        lower_input = user_input.lower()

        # Time-related queries
        if any(kw in lower_input for kw in ["time", "date", "day"]):
            tool = self.tool_registry.get("get_datetime_info")
            if tool:
                result = await self.tool_executor.execute(
                    tool, {"query": user_input}, permission_profile=permission_profile
                )
                if result.success:
                    return (result.result, "get_datetime_info")
                return ("Could not get time info.", None)

        # System status
        if any(kw in lower_input for kw in ["system", "cpu", "memory", "status"]):
            tool = self.tool_registry.get("system_status")
            if tool:
                result = await self.tool_executor.execute(
                    tool, {}, permission_profile=permission_profile
                )
                if result.success:
                    return (result.result, "system_status")
                return ("Could not get system status.", None)

        # Task listing
        if "task" in lower_input and any(kw in lower_input for kw in ["list", "show", "what"]):
            tool = self.tool_registry.get("list_tasks")
            if tool:
                result = await self.tool_executor.execute(
                    tool, {}, permission_profile=permission_profile
                )
                if result.success:
                    return (result.result, "list_tasks")
                return ("Could not list tasks.", None)

        return (
            "GEMINI_API_KEY is not configured. I can only perform basic commands. "
            "Set the GEMINI_API_KEY in your .env file for full AI capabilities.",
            None,
        )

    async def _execute_function_call(
        self,
        function_call: Any,
        permission_profile: PermissionProfile = PermissionProfile.SYSTEM_FULL,
    ) -> str:
        """Execute a Gemini function call."""
        tool_name = function_call.name
        args = dict(function_call.args) if getattr(function_call, "args", None) else {}

        # Increment Prometheus tool call counter
        try:
            from src.infra.metrics import amadeus_tool_calls_total

            amadeus_tool_calls_total.labels(tool_name=tool_name).inc()
        except Exception:
            pass  # metrics unavailable in test / CLI context

        # Check tool cache
        if self.cache_service:
            cached_result = await self.cache_service.get_tool_result(tool_name, args)
            if cached_result:
                logger.debug("Tool cache hit for '%s'", tool_name)
                # Update cache hit rate gauge
                try:
                    from src.infra.metrics import amadeus_cache_hit_rate

                    stats = self.cache_service.get_stats()
                    amadeus_cache_hit_rate.set(stats["hit_rate_pct"])
                except Exception:
                    pass
                return cached_result

        tool = self.tool_registry.get(tool_name)
        if not tool:
            return f"Tool '{tool_name}' not found"

        result = await self.tool_executor.execute(tool, args, permission_profile=permission_profile)

        if result.success:
            result_str = str(result.result)
            if self.cache_service:
                await self.cache_service.set_tool_result(tool_name, args, result_str)
            return result_str
        return result.error_message or "Tool execution failed"

    async def _generate_conversational_response(self, user_input: str) -> str:
        """Generate a response without any tools."""
        current_time = datetime.now().strftime("%I:%M %p on %A, %B %d")
        context = self.conversation_manager.get_formatted_history(3)

        # Inject long-term memories for conversational turns too
        long_term_memories = await self.memory_service.retrieve(user_input, top_k=3)
        memory_context = self.memory_service.format_for_prompt(long_term_memories, max_chars=600)

        prompt = f"""{
            self.identity_prompt.format(
                current_time=current_time,
                session_id=self.session_id,
                context_summary=self.conversation_manager.get_context_summary(),
            )
        }
{memory_context}

Recent conversation:
{context}

User: {user_input}

Respond naturally and conversationally. Be concise."""

        try:
            # 💡 Use LLMRouter if available to save Gemini quota (will use Groq/Llama3 if possible)
            if hasattr(self, "llm_router") and self.llm_router:
                response_text, provider = await self.llm_router.generate(prompt=prompt, complexity="normal")
                logger.info(f"Conversational response handled by router (Provider: {provider})")
                return response_text

            assert self.client is not None, "Gemini client not initialized"
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
            return str(response.text) if hasattr(response, "text") else str(response)
        except Exception as e:
            logger.exception(f"Error generating response: {e}")
            return "I'm having trouble responding right now."

    async def _generate_response_with_result(
        self, user_input: str, tool_name: str, result: str
    ) -> str:
        """Generate a natural response incorporating a tool result."""
        prompt = f"""You just executed the '{tool_name}' tool for the user.

User request: {user_input}
Tool result: {result}

Provide a natural, concise response that incorporates this result. Don't just repeat the result - present it helpfully."""

        try:
            assert self.client is not None, "Gemini client not initialized"
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
            return str(response.text) if hasattr(response, "text") else result
        except Exception:
            return result  # Fallback to raw result

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def get_tool_summary(self) -> dict:
        """Get a summary of registered tools."""
        return self.tool_registry.get_summary()

    async def clear_conversation(self) -> None:
        """Clear conversation history (from cache, DB, and long-term vector memory)."""
        await self.conversation_manager.clear()
        await self.memory_service.clear_session(self.session_id)

    async def shutdown(self) -> None:
        """Cleanup orchestrator background tasks."""
        if hasattr(self, "orchestrator"):
            await self.orchestrator.shutdown()

    # =========================================================================
    # OUTBOUND MESSAGING (SCHEDULER / PROACTIVE)
    # =========================================================================

    async def send_outbound_message(self, user_id: str, platform: str, message: str) -> bool:
        """
        Send an outbound message proactively (e.g., from a background task or cron job).

        Args:
            user_id: The ID of the user on the target platform
            platform: 'telegram' or 'whatsapp'
            message: The content of the message to send

        Returns:
            bool: True if sent successfully, False otherwise
        """
        try:
            logger.info(f"Preparing outbound {platform} message to {user_id}...")

            # Store it in the conversation history as an assistant message
            # If the user_id corresponds to the active session_id, this keeps context sync'd
            await self.conversation_manager.add(
                role="assistant", content=message, metadata={"outbound": True, "platform": platform}
            )

            # Dispatch to the correct adapter
            platform_lower = platform.lower()
            if platform_lower == "telegram":
                adapter = TelegramAdapter()
                await adapter.send_message(int(user_id), message)
                return True

            if platform_lower == "whatsapp":
                wa_adapter = WhatsAppAdapter()
                await wa_adapter.send_message(user_id, message)
                return True

            logger.error(f"Unsupported outbound platform: {platform}")
            return False

        except Exception as e:
            logger.error(
                f"Failed to send outbound message to {user_id} on {platform}: {e}", exc_info=True
            )
            return False
