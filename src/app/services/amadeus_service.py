"""
Amadeus Service - Main AI Assistant Orchestrator.

This service uses a local-first, zero-training semantic routing architecture.
It triages user intent in two stages:
  1. SemanticToolRouter — embeds the query and performs cosine similarity
     against all tool description vectors (sentence-transformers, all-mpnet-base-v2).
     No retraining required; new tools are hot-plugged automatically.
  2. Local LLM (LlamaCpp) — fallback when the semantic router confidence
     is below threshold, handling conversational or cloud-escalation paths.

Architecture:
- Public API: handle_command, get_response
- Internal Logic: _process_command_internal, _predict_intent_llm
- Infrastructure: tool registry, semantic_router, conversation manager, voice services
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
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


from google import genai
from google.genai import types

from src.app.services.semantic_router import SemanticToolRouter
from src.app.services.tool_registry import ToolRegistry
from src.core.config import Settings, get_settings
from src.core.domain.models import PermissionProfile
from src.infra.knowledge_graph import KnowledgeGraphService
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
        
        # Knowledge Graph (Tier 2 episodic memory)
        self.kg_service = KnowledgeGraphService()

        if self.memory_service.is_enabled:
            logger.info("Tiered memory system ENABLED — Qdrant + KG ready")
        else:
            logger.info("Long-term memory DISABLED — operating with session-only context")

        # Initialize components
        self._load_api_keys()
        self._register_all_tools()

        # Build zero-training semantic tool router
        self._semantic_router = SemanticToolRouter(
            registry=self.tool_registry,
            model_dir=self.settings.BASE_DIR / "Model",
            threshold=0.50,
        )
        self._semantic_router.build_index()

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
                if self.client is None:
                    raise ValueError("client is missing")
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

    def _register_all_tools(self) -> None:
        """Register all tools from the tool modules."""
        # Import and register tools from each module
        try:
            from src.infra.tools.agent_tools import get_agent_tools
            from src.infra.tools.filesystem_tools import build_filesystem_tools
            from src.infra.tools.info_tools import get_info_tools
            from src.infra.tools.monitor_tools import get_monitor_tools
            from src.infra.tools.productivity_tools import get_productivity_tools
            from src.infra.tools.system_control_tools import get_system_control_tools
            from src.infra.tools.system_tools import get_system_tools

            for tool in get_info_tools():
                self.tool_registry.register(tool)
            for tool in get_system_tools():
                self.tool_registry.register(tool)
            for tool in get_system_control_tools():
                self.tool_registry.register(tool)
            for tool in get_monitor_tools():
                self.tool_registry.register(tool)
            for tool in get_productivity_tools():
                self.tool_registry.register(tool)
            for tool in get_agent_tools():
                self.tool_registry.register(tool)
            for tool in build_filesystem_tools():
                self.tool_registry.register(tool)

            # Developer / sandbox tools (Docker-based code execution)
            try:
                from src.infra.tools.developer_tools import get_developer_tools

                for tool in get_developer_tools():
                    self.tool_registry.register(tool)
            except Exception as e:
                logger.warning("Failed to register developer_tools: %s", e)

            # Workspace search tool (Omni-Workspace RAG)
            try:
                from src.infra.tools.workspace_tools import get_workspace_tools

                for tool in get_workspace_tools():
                    self.tool_registry.register(tool)
            except Exception as e:
                logger.warning("Failed to register workspace_tools: %s", e)

            logger.info(f"Registered {len(self.tool_registry)} tools from modules")
        except Exception as e:
            logger.exception(f"Error registering tools: {e}")

    def _build_identity_prompt(self) -> str:
        """Build the operational system prompt for Amadeus.

        Identity (who Amadeus is, its memories, creator) is stored in the
        Qdrant/KG memory layer and injected dynamically via _get_system_prompt.
        This base prompt focuses purely on OPERATIONAL RULES and AGENTIC BEHAVIOR.
        """
        return """SYSTEM: AMADEUS — OPERATIONAL DIRECTIVES

You are Amadeus, an advanced autonomous AI assistant.

--------------------------------------------------

AGENTIC CAPABILITIES (OpenClaw-style autonomous operations)

You are NOT a passive chatbot. You are an active agentic system that:
- Reads and writes files on the local filesystem
- Launches, monitors, and terminates OS processes
- Manages email, calendars, and communication platforms
- Sets system controls (volume, brightness, screenshots)
- Searches the web, Wikipedia, and local data
- Executes Python code in a secure sandbox
- Chains multiple tools sequentially to complete complex goals

When a user makes a request, ALWAYS:
1. Identify whether a tool can fulfill it — tools take priority over conversation.
2. Extract arguments precisely from the user's natural language.
3. Use tools; do NOT hallucinate results.
4. Compose a clear, concise response around the tool output.

--------------------------------------------------

RULES OF ENGAGEMENT

1. TOOLS BEFORE CONJECTURE
   - If you can fetch data via a tool, do it — never guess or fabricate.

2. PRECISION
   - Be direct and concise. No unnecessary preambles.
   - Do not repeat what the tool returned verbatim — synthesize it.

3. HONESTY
   - If a request is impossible or the tool failed, say so clearly.
   - Never pretend a failed tool succeeded.

4. CONTEXT ADAPTATION
   - Technical request → structured and precise.
   - Casual conversation → slightly relaxed, but always sharp.

5. MEMORY-DRIVEN
   - Relevant retrieved memories (injected below) inform your responses.
   - Do NOT fabricate memories that weren't retrieved.

6. FAIL-SAFE
   - If a user request conflicts with facts, logic, or system constraints:
     challenge it and provide a correct alternative.

--------------------------------------------------

RESPONSE FORMAT

- 1–3 sentences for simple answers.
- Structured output (lists, steps) for complex tasks.
- No emojis unless contextually appropriate.
- No generic filler phrases ("Of course!", "Great question!").

--------------------------------------------------

Current time: {current_time}
Session ID: {session_id}
Context: {context_summary}"""

    async def _get_system_prompt(self, user_query: str = "") -> str:
        """
        Return the tiered system prompt incorporating Identity, KG facts, and Semantic Memory.
        """
        current_time = datetime.now().strftime("%I:%M %p on %A, %B %d")
        context_summary = self.conversation_manager.get_context_summary()

        # Tier 1: Core Identity (Base Prompt)
        base_prompt = self.identity_prompt.format(
            current_time=current_time,
            session_id=self.session_id,
            context_summary=context_summary,
        )

        kg_facts = ""
        memories_context = ""

        if user_query and self.memory_service.is_enabled:
            # Tier 2: Knowledge Graph facts (Exact recall)
            facts = await self.kg_service.retrieve_triples(user_query, limit=2)
            if facts:
                kg_facts = "\n[RELEVANT KG FACTS]\n" + "\n".join(f"- {f}" for f in facts)

            # Tier 3: Semantic Memories (Weighted ranking)
            memories = await self.memory_service.retrieve(user_query, top_k=3)
            if memories:
                # Use the new formatted retrieval
                memories_context = "\n[RETRIEVED MEMORIES]\n" + self.memory_service.format_for_prompt(memories)

        prompt_parts = [base_prompt]
        if kg_facts:
            prompt_parts.append(kg_facts)
        if memories_context:
            prompt_parts.append(memories_context)
            
        return "\n".join(prompt_parts) + "\n\n[USER MESSAGE]\n"

    # =========================================================================
    # TRIAGE & ROUTING
    # =========================================================================

    async def _predict_intent_llm(self, query: str) -> tuple[str, str | None]:
        """
        Two-stage intent triaging:

        Stage 1 — SemanticToolRouter (zero-training, pure cosine similarity).
                   Embeds the query and compares against all tool description
                   vectors. No retraining required when adding new tools.
        Stage 2 — Local LLM (LlamaCpp) fallback when semantic confidence is
                   below threshold or the router is not yet initialised.

        Decides: tool (and which one), conversational, or cloud_escalation.
        """
        # --- Stage 1: Semantic Router (sentence-transformers cosine similarity) ---
        if self._semantic_router.is_ready:
            matched_tool = self._semantic_router.route(query)
            if matched_tool:
                return "tool", matched_tool

        # --- Stage 2: LLM fallback ---
        if not self.llm_router:
            return "conversational", None

        tools_menu = self.tool_registry.get_tools_menu()
        triage_prompt = f"""### Instructions
You are the semantic router for Amadeus AI. Classify the user's request.

### Available Tools
{tools_menu}

### Decision Rules
1. If the request matches a tool, output EXACTLY: ACTION: <tool_name>
2. Greeting / small-talk / general chat → ACTION: conversational
3. Highly complex (advanced code, math, philosophy) → ACTION: cloud_escalation

### User Input
{query}

### Decision
"""

        try:
            response, _provider = await self.llm_router.generate(
                prompt=triage_prompt,
                complexity="simple",
                temperature=0.0,
                max_tokens=20,
            )

            clean_res = response.strip().upper()
            if "ACTION: CLOUD_ESCALATION" in clean_res:
                return "cloud_escalation", None
            if "ACTION: CONVERSATIONAL" in clean_res:
                return "conversational", None

            # Check for a matching tool name in the response
            for t_name in self.tool_registry.list_names():
                if t_name.upper() in clean_res:
                    return "tool", t_name

            return "conversational", None

        except Exception as e:
            logger.error("LLM semantic triage failed: %s", e)
            return "conversational", None


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
            # Subtype 'interaction' with standard importance
            await self.memory_service.store(
                self.session_id, "user", user_input, subtype="interaction", importance=0.5
            )

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
            await self.memory_service.store(
                self.session_id, "assistant", response, subtype="interaction", importance=0.4
            )

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
        Internal command processing — Semantic Triage Routing.

        Flow:
        0. Semantic Triage (LlamaCpp): Decides action type locally:
           - 'tool': specific localized tool execution.
           - 'conversational': handled as local chat unless complexity warrants cloud.
           - 'cloud_escalation': immediately routes to cloud LLM (Groq/Gemini).
        1. Tool Execution: If triage identifies a tool, it is executed locally.
        2. Composition: Results are composed into a natural response using LLMRouter.

        Returns:
            Tuple of (response_text, tool_used_name or None)
        """
        # ── Step 0: Semantic Triage (Local LLM) ───────────────────────────────
        # Use the local model to decide: Tool, Chat, or Cloud Escalation.
        # This replaces the heuristic ComplexityScorer and the statistical SVM.
        intent_type, tool_name = await self._predict_intent_llm(user_input)

        if intent_type == "cloud_escalation":
            logger.info("Local triage: High complexity detected — escalating to Cloud LLM.")
            response = await self._generate_conversational_response(
                user_input, forced_complexity="high"
            )
            return (response, None)

        if intent_type == "conversational":
            logger.info("Local triage: Handling as conversational chat.")
            response = await self._generate_conversational_response(user_input)
            return (response, None)

        # ── Step 1: Tool execution (Local or Cloud-assisted args) ────────────
        # 'intent_type' was 'tool', and 'tool_name' holds our target.
        actual_tool_name = tool_name or ""
        tool = self.tool_registry.get(actual_tool_name)

        if tool:
            # Extract args from user input using keyword parsing / LLM
            args = await self._extract_args_for_tool(actual_tool_name, user_input)

            # ── Per-tool-category timeout fail-safes ─────────────────────────
            # sandbox / developer tools can legitimately run longer (code exec);
            # I/O-bound tools (web, email) get a generous but finite window;
            # local OS / monitor tools should always be fast.
            TOOL_TIMEOUTS = {
                "execute_python_script": 300,  # sandbox
                "web_search": 30,
                "get_weather": 20,
                "get_news": 20,
                "wikipedia_search": 20,
                "send_email": 30,
                "read_unread_emails": 30,
                "create_excel_spreadsheet": 60,
                "create_word_document": 60,
            }
            timeout_s = TOOL_TIMEOUTS.get(actual_tool_name, 15)  # default 15 s

            try:
                result = await asyncio.wait_for(
                    self.tool_executor.execute(
                        tool, args, permission_profile=permission_profile
                    ),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Tool '%s' timed out after %ds", actual_tool_name, timeout_s
                )
                return (
                    f"The {actual_tool_name} tool took too long to respond ({timeout_s}s). "
                    "Please try again or simplify your request.",
                    actual_tool_name,
                )

            if result.success:
                # Use LLMRouter (Llama/Groq) to compose a natural response.
                response_text = await self._compose_tool_response_locally(
                    user_input, actual_tool_name, str(result.result)
                )
                return (response_text, actual_tool_name)
            # Tool failed — tell user clearly
            return (
                f"I tried to use {actual_tool_name} but encountered an issue: {result.error_message}",
                actual_tool_name,
            )

        # Step 4: Tool not in registry — fall back to Gemini if available
        if getattr(self, "client", None):
            return await self._process_with_gemini(user_input, [actual_tool_name], permission_profile)

        return (
            "I couldn't find the right tool for that. Try rephrasing your request.",
            None,
        )

    async def _extract_args_for_tool(self, tool_name: str, user_input: str) -> dict:
        """
        Extract tool arguments from user input using robust LLM JSON parsing
        with keyword/pattern matching as a fallback fast-path.
        """
        text = user_input.strip()
        lower = text.lower()

        # ── Office tools: require structured args (columns, data) ─────────
        if tool_name == "create_excel_spreadsheet":
            return await self._extract_excel_args(text)
        if tool_name == "create_word_document":
            return await self._extract_word_args(text)

        # ── Universal LLM Extraction for robust natural language parsing ──
        tool = self.tool_registry.get(tool_name)
        if tool and getattr(tool, "parameters", None) and hasattr(self, "llm_router") and self.llm_router:
            # Use LLM for sentences with diverse adjectives/phrasing
            if len(text.split()) > 2:
                llm_extracted = await self._extract_args_with_llm(tool_name, text, tool.parameters)
                if llm_extracted and isinstance(llm_extracted, dict):
                    valid_keys = list(tool.parameters.keys())
                    clean_extracted = {k: str(v).strip() for k, v in llm_extracted.items() if k in valid_keys and str(v).strip()}
                    if clean_extracted:
                        return clean_extracted

        # ── Fast-path Fallbacks (Regexes) ──
        if tool_name == "open_program":
            for kw in ["open ", "launch ", "start ", "run "]:
                if kw in lower:
                    app = text[lower.index(kw) + len(kw) :].strip()
                    return {"app_name": app}
            return {"app_name": text}

        if tool_name == "terminate_program":
            for kw in ["close ", "kill ", "stop ", "terminate ", "end "]:
                if kw in lower:
                    app = text[lower.index(kw) + len(kw) :].strip()
                    return {"process_name": app}
            return {"process_name": text}

        if tool_name == "search_file":
            lower_text = lower.replace("a pdf named ", "").replace("a file named ", "")
            for kw in ["find ", "locate ", "where is ", "search for ", "search "]:
                if kw in lower_text:
                    return {"file_name": text.lower().replace("a pdf named ", "").replace("a file named ", "")[lower_text.index(kw) + len(kw) :].strip()}
            return {"file_name": text}

        if tool_name in ("web_search", "wikipedia_search"):
            import re as _re

            q = text
            # ── Pass 1: strip leading conversational prefixes ──────────────────
            # Order matters: longer/more-specific patterns first.
            _prefix_patterns = [
                r"^(?:amadeus[,]?\s+)?(?:please\s+)?(?:can you\s+)?(?:could you\s+)?"
                r"(?:search for|search|look up|google|find info(?:rmation)? (?:about|on)|tell me about|explain|who is|what is|give me info(?:rmation)? (?:about|on)|find|get info(?:rmation)? (?:about|on)|research)\s+",
            ]
            for pat in _prefix_patterns:
                cleaned = _re.sub(pat, "", q, flags=_re.IGNORECASE).strip()
                if cleaned and cleaned.lower() != q.lower():
                    q = cleaned
                    break
            # Also strip a bare leading 'Amadeus' followed by optional comma/space
            q = _re.sub(r"^amadeus[,]?\s+", "", q, flags=_re.IGNORECASE).strip()
            # ── Pass 2: strip trailing noise phrases ──────────────────────────
            _suffix_patterns = [
                r"\s+(?:on|from|in|via|using)\s+wikipedia$",
                r"\s+(?:on|from|in|via|using)\s+google$",
                r"\s+(?:on|from)\s+the\s+(?:web|internet|net)$",
                r"\s+for\s+me$",
                r"\s+please$",
            ]
            for pat in _suffix_patterns:
                q = _re.sub(pat, "", q, flags=_re.IGNORECASE).strip()
            return {"query": q if q else text}

        if tool_name == "get_weather":
            import re
            match = re.search(r"weather(?:\s+forecast)?\s+(?:today\s+)?(?:in|at|for)\s+([a-zA-Z\s]+)", lower)
            if match:
                return {"location": match.group(1).strip()}
            # Also handle simple "london weather" or "weather london"
            text_cleaned = list(filter(lambda x: x not in ["how", "what", "is", "the", "weather", "today", "like", "in"], lower.split()))
            if text_cleaned:
                return {"location": " ".join(text_cleaned)}
            return {"location": "current location"}

        if tool_name == "get_news":
            import re as _re

            # Parse country from patterns like "news from usa", "us news", "india news"
            country_map = {
                "usa": "us", "us": "us", "america": "us", "american": "us",
                "india": "in", "indian": "in",
                "uk": "gb", "britain": "gb", "england": "gb",
                "australia": "au", "canada": "ca",
            }
            country = "in"  # default
            for kw, code in country_map.items():
                if kw in lower:
                    country = code
                    break

            # Parse category from keywords
            cat_map = {
                "tech": "technology", "technology": "technology",
                "business": "business", "finance": "business", "economy": "business",
                "sports": "sports", "sport": "sports",
                "health": "health", "medical": "health",
                "science": "science",
                "entertainment": "entertainment", "bollywood": "entertainment",
                "political": "general", "politics": "general", "wars": "general",
            }
            category = "general"
            for kw, cat in cat_map.items():
                if kw in lower:
                    category = cat
                    break

            return {"category": category, "country": country, "count": 5}

        if tool_name == "set_volume":
            import re as _re

            # Patterns: "set volume to 50", "volume 70%", "volume up", "mute"
            if "mute" in lower:
                return {"level": -1}
            if "unmute" in lower:
                return {"level": -2}
            match = _re.search(r"(\d+)\s*%?", lower)
            if match:
                return {"level": int(match.group(1))}
            if "max" in lower or "full" in lower:
                return {"level": 100}
            if "half" in lower:
                return {"level": 50}
            return {"level": 50}  # safe default

        if tool_name == "set_brightness":
            import re as _re

            match = _re.search(r"(\d+)\s*%?", lower)
            if match:
                return {"level": int(match.group(1))}
            if "max" in lower or "full" in lower:
                return {"level": 100}
            if "low" in lower or "dim" in lower:
                return {"level": 20}
            if "half" in lower:
                return {"level": 50}
            return {"level": 70}  # safe default

        if tool_name in ("take_screenshot", "get_volume",
                         "list_open_apps", "get_battery_info",
                         "system_status", "get_running_processes",
                         "get_cpu_usage", "get_memory_usage",
                         "get_disk_usage", "get_network_info"):
            return {}  # no args needed

        if tool_name == "calculate":
            for kw in ["calculate ", "compute ", "what is ", "evaluate "]:
                if kw in lower:
                    return {"expression": text[lower.index(kw) + len(kw) :].strip()}
            return {"expression": text}

        if tool_name == "create_note":
            for kw in ["note ", "note: ", "save note "]:
                if kw in lower:
                    return {"content": text[lower.index(kw) + len(kw) :].strip()}
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

    async def _extract_args_with_llm(self, tool_name: str, user_input: str, schema: dict) -> dict | None:
        """Use LLM to dynamically parse natural-language requests into parameters based on schema."""
        extraction_prompt = (
            f"You are a strict JSON extraction assistant. The user wants to execute the '{tool_name}' tool.\n"
            f"Here is the parameter schema for this tool:\n{schema}\n\n"
            "Extract the parameter values precisely from the user's request based on this schema.\n"
            "Strip out all conversational noise, adjectives, and polite phrases.\n"
            "Return ONLY a valid JSON object. No markdown fences, no explanations.\n"
            "If a parameter cannot be logically extracted from the text, omit it or use an empty string.\n\n"
            f'User request: "{user_input}"'
        )
        try:
            raw_text, provider = await self.llm_router.generate(
                prompt=extraction_prompt, complexity="low"
            )
            logger.debug(f"LLM args extracted by {provider} for {tool_name}")
            import json

            clean = raw_text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()
            parsed = json.loads(clean)
            return parsed
        except Exception as e:
            logger.warning("LLM generalized arg extraction failed for '%s': %s", tool_name, e)
            return None

    async def _extract_excel_args(self, user_input: str) -> dict:
        """Use LLM to parse a natural-language Excel request into structured args."""
        extraction_prompt = (
            "You are a JSON extraction assistant. The user wants to create an Excel spreadsheet.\n"
            "From the request below, extract:\n"
            '  - "file_name": a suitable .xlsx filename (snake_case, no spaces)\n'
            '  - "columns": a list of column header strings\n'
            '  - "data": a list of lists, where each inner list is one row of data matching the columns\n\n'
            "Return ONLY valid JSON. No explanation, no markdown fences, just the JSON object.\n\n"
            f'User request: "{user_input}"'
        )
        try:
            if hasattr(self, "llm_router") and self.llm_router:
                raw_text, provider = await self.llm_router.generate(
                    prompt=extraction_prompt, complexity="normal"
                )
                logger.info("Excel args extracted by %s", provider)
                import json

                # Strip markdown code fences if present
                clean = raw_text.strip()
                if clean.startswith("```"):
                    clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                if clean.endswith("```"):
                    clean = clean[:-3]
                clean = clean.strip()
                parsed = json.loads(clean)
                return {
                    "file_name": parsed.get("file_name", "spreadsheet.xlsx"),
                    "columns": parsed.get("columns", []),
                    "data": parsed.get("data", []),
                }
        except Exception as e:
            logger.warning("LLM Excel arg extraction failed: %s — using defaults", e)

        # Fallback: create an empty spreadsheet with a sensible name
        return {
            "file_name": "spreadsheet.xlsx",
            "columns": ["Column1", "Column2", "Column3"],
            "data": [],
        }

    async def _extract_word_args(self, user_input: str) -> dict:
        """Use LLM to parse a natural-language Word document request into structured args."""
        extraction_prompt = (
            "You are a JSON extraction assistant. The user wants to create a Word document.\n"
            "From the request below, extract:\n"
            '  - "file_name": a suitable .docx filename (snake_case, no spaces)\n'
            '  - "title": the document title\n'
            '  - "content": the full body text for the document\n\n'
            "Return ONLY valid JSON. No explanation, no markdown fences, just the JSON object.\n\n"
            f'User request: "{user_input}"'
        )
        try:
            if hasattr(self, "llm_router") and self.llm_router:
                raw_text, provider = await self.llm_router.generate(
                    prompt=extraction_prompt, complexity="normal"
                )
                logger.info("Word args extracted by %s", provider)
                import json

                clean = raw_text.strip()
                if clean.startswith("```"):
                    clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                if clean.endswith("```"):
                    clean = clean[:-3]
                clean = clean.strip()
                parsed = json.loads(clean)
                return {
                    "file_name": parsed.get("file_name", "document.docx"),
                    "title": parsed.get("title", "Untitled Document"),
                    "content": parsed.get("content", ""),
                }
        except Exception as e:
            logger.warning("LLM Word arg extraction failed: %s — using defaults", e)

        return {
            "file_name": "document.docx",
            "title": "Untitled Document",
            "content": user_input,
        }

    async def _compose_tool_response_locally(
        self, user_input: str, tool_name: str, tool_result: str
    ) -> str:
        """
        Use LLMRouter to compose a friendly response incorporating the tool result.
        complexity='auto' so the scorer can escalate to cloud when the original
        user request was itself complex (e.g. 'explain this code').
        """
        prompt = (
            f"The user asked: '{user_input}'\n"
            f"You ran the tool '{tool_name}' and got this result:\n{tool_result}\n\n"
            f"Compose a brief, natural, conversational response to the user based on this result. "
            f"Be concise — 1-2 sentences max. "
            f"If the result says 'not found' or contains an error, apologise briefly and suggest "
            f"the user try rephrasing with just the topic name (e.g. 'Alexander the Great' "
            f"instead of a full sentence). Do NOT repeat the raw error message verbatim."
        )
        try:
            if hasattr(self, "llm_router") and self.llm_router:
                text, provider = await self.llm_router.generate(prompt=prompt, complexity="auto")
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
        system_prompt = await self._get_system_prompt(user_input)

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
            if self.client is None:
                raise ValueError("client is missing")
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

    async def _generate_conversational_response(
        self, user_input: str, forced_complexity: str | None = None
    ) -> str:
        """Generate a response without any tools.

        Args:
            user_input: The raw user message.
            forced_complexity: If set, overrides auto-scoring and pins the
                complexity passed to LLMRouter (e.g. 'high' for code/creative
                tasks detected by the pre-SVM gate).
        """
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

        # Determine complexity: caller-forced level takes precedence over auto-scoring.
        complexity = forced_complexity if forced_complexity else "auto"

        try:
            if hasattr(self, "llm_router") and self.llm_router:
                response_text, provider = await self.llm_router.generate(
                    prompt=prompt, 
                    complexity=complexity,
                    max_tokens=2048 if complexity == "high" else None
                )
                logger.info(
                    "Conversational response: provider=%s complexity=%s",
                    provider,
                    complexity,
                )
                return response_text

            if self.client is None:
                raise ValueError("Gemini client not initialized")
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
            if self.client is None:
                raise ValueError("Gemini client not initialized")
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
