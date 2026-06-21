"""
Amadeus Service - main AI assistant orchestrator.

This module is intentionally thin. All heavy logic lives in focused sub-services:

  ConversationManager  - history storage, in-memory cache, DB sync
  UnifiedSemanticRouter - embedding-based intent triage
  ArgumentExtractor    - NLP to tool argument dicts (LLM + regex)
  ToolDispatcher       - tool lookup, execution, timeouts, result caching
  ResponseComposer     - LLM prose generation, system prompt building

Architecture:
  Public API : handle_command()
  Routing    : _predict_intent() through UnifiedSemanticRouter
  Processing : _process_command_internal()
  Delegation : _process_with_agent() for multi-step queries
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from opentelemetry import trace

from src.app.services.argument_extractor import ArgumentExtractor
from src.app.services.conversation_manager import ConversationManager, IConversationRepository
from src.app.services.messaging_service import MessagingService
from src.app.services.response_composer import ResponseComposer
from src.app.services.semantic_router import UnifiedSemanticRouter
from src.app.services.tool_dispatcher import ToolDispatcher
from src.app.services.tool_registry import ToolRegistry
from src.core.config import Settings, get_settings
from src.core.domain.context import RequestContext
from src.core.interfaces.repositories import IGoalRepository
from src.infra.queue.manager import QueueManager
from src.infra.tools.base import ToolExecutor
from src.infra.turbovec_memory import TurbovecMemoryService


if TYPE_CHECKING:
    from src.infra.cache.cache_service import CacheService
    from src.infra.llm.router import LLMRouter

logger = logging.getLogger(__name__)


class AmadeusService:
    """
    Thin orchestrator that coordinates the Amadeus AI sub-services.

    Responsibilities (only these — nothing else):
      1. Wire sub-services at construction time.
      2. Accept user input via handle_command().
      3. Route: multi-step → AmadeusGraph (LangGraph), single-step → sub-services.
      4. Persist conversation turns and long-term memories.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        tool_registry: ToolRegistry | None = None,
        conversation_repo: IConversationRepository | None = None,
        goal_repository: IGoalRepository | None = None,

        debug_mode: bool = False,
        cache_service: CacheService | None = None,
        auto_start_orchestrator: bool = True,
        llm_router: LLMRouter | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.debug_mode = debug_mode
        self.cache_service = cache_service

        self.client: Any | None = None  # genai.Client when GEMINI_API_KEY is set
        self.model_name: str = self.settings.GEMINI_MODEL
        self._conversation_repo = conversation_repo
        self.goal_repository = goal_repository

        # ── LLM Router ────────────────────────────────────────────────
        if llm_router:
            self.llm_router: LLMRouter | None = llm_router
        else:
            try:
                from src.container import get_llm_router
                self.llm_router = get_llm_router()
            except Exception:
                self.llm_router = None

        # ── Tool Registry (injected — never built here) ───────────────
        self.tool_registry = tool_registry or ToolRegistry()

        # ── Tool Executor ─────────────────────────────────────────────
        self.tool_executor = ToolExecutor()

        # ── Task Queue ────────────────────────────────────────────────
        self.queue_manager = QueueManager(redis_url=self.settings.REDIS_URL)

        # ── Messaging Service ──────────────────────────────────────────
        # Note: Telegram transport is often initialized after AmadeusService
        # because of the circular dependency with runtime.
        self.messaging = MessagingService()



        # ── Long-term Memory (Turbovec) ────────────────────────────
        self.memory_service = TurbovecMemoryService(settings=self.settings)

        if self.memory_service.is_enabled:
            logger.info("Tiered memory system ENABLED — Turbovec ready")
        else:
            logger.info("Long-term memory DISABLED — operating with session-only context")

        # ── Gemini direct client (LOCAL_ONLY_MODE blocks actual calls) ─
        self._load_api_keys()

        # ── Semantic Router ───────────────────────────────────────────
        self._semantic_router = UnifiedSemanticRouter(
            registry=self.tool_registry,
            model_dir=self.settings.BASE_DIR / "Model",
            threshold=self.settings.SEMANTIC_ROUTER_THRESHOLD,
        )

        # ── Sub-services ──────────────────────────────────────────────
        self._arg_extractor = ArgumentExtractor(
            tool_registry=self.tool_registry,
            llm_router=self.llm_router,
        )
        self._tool_dispatcher = ToolDispatcher(
            tool_registry=self.tool_registry,
            tool_executor=self.tool_executor,
            cache_service=self.cache_service,
        )
        self._composer = ResponseComposer(
            llm_router=self.llm_router,
            settings=self.settings,
            memory_service=self.memory_service,
        )

        # ── LangGraph Agent (multi-step) ─────────────────────────────
        from src.app.services.agent_loop import AmadeusGraph

        # AsyncSqliteSaver is opened in initialize() so we have a running
        # event loop. Store the path and CM reference here; the graph is
        # also built there once the checkpointer is ready.
        self._checkpoint_db_path = self.settings.BASE_DIR / "langgraph_checkpoints.sqlite"
        self._checkpointer_cm = None  # async context manager handle
        self._checkpointer = None

        llm_generate = self._make_llm_generate()
        self.graph = AmadeusGraph(
            tool_registry=self.tool_registry,
            tool_executor=self.tool_executor,
            llm_generate=llm_generate,
            memory_service=self.memory_service,
            checkpointer=None,  # patched in initialize()
        )

        logger.info(
            "AmadeusService initialized — %d tools...",
            len(self.tool_registry),
        )

    # ------------------------------------------------------------------
    # Async initialization
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Async startup: warm memory service and hydrate conversation cache from DB."""
        await self.memory_service.initialize()
        await self.queue_manager.initialize()

        # Open the async SQLite checkpointer now that the event loop is running.
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        self._checkpointer_cm = AsyncSqliteSaver.from_conn_string(
            str(self._checkpoint_db_path)
        )
        self._checkpointer = await self._checkpointer_cm.__aenter__()
        # Patch the already-constructed graph with the live checkpointer.
        self.graph.set_checkpointer(self._checkpointer)
        logger.info("AsyncSqliteSaver checkpointer ready: %s", self._checkpoint_db_path)

        if not self._semantic_router.is_ready:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._semantic_router.build_index)
            logger.info(
                "SemanticRouter ready=%s after build attempt",
                self._semantic_router.is_ready
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def handle_command(
        self,
        user_input: str,
        context: RequestContext,
        source: str = "text",
    ) -> str:
        """
        Main entry point. Returns the assistant's response as a string.

        ``context`` is passed per call so singleton service instances are
        safe under concurrent requests.
        """
        if not user_input.strip():
            return "I didn't catch that. Could you repeat?"

        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("AmadeusService.handle_command") as span:
            span.set_attribute("context.session_id", context.session_id)
            span.set_attribute("context.user_id", context.user_id)
            span.set_attribute("input.source", source)

            active_session_id = context.session_id
            conversation_manager = await self._get_conversation_manager(active_session_id)

            try:
                await conversation_manager.add("user", user_input)
                await self.memory_service.store(
                    active_session_id, "user", user_input, subtype="interaction", importance=0.5
                )

                if self._is_multi_step_query(user_input):
                    response, tools_used = await self._process_with_agent(
                        user_input,
                        conversation_manager=conversation_manager,
                        context=context,
                    )
                    tool_used = ", ".join(tools_used) if tools_used else None
                else:
                    response, tool_used = await self._process_command_internal(
                        user_input,
                        conversation_manager=conversation_manager,
                        context=context,
                    )

                await conversation_manager.add("assistant", response, tool_used=tool_used)
                await self.memory_service.store(
                    active_session_id, "assistant", response, subtype="interaction", importance=0.4
                )
                return response

            except Exception as exc:
                from src.app.services.agent_loop import QueueFullError

                if isinstance(exc, QueueFullError):
                    span.record_exception(exc)
                    raise

                logger.error("Error handling command: %s", exc, exc_info=True)
                span.record_exception(exc)
                if self.debug_mode or getattr(self.settings, "ALLOW_DEBUG_RESPONSES", False):
                    return f"I encountered an error ({type(exc).__name__}). Check the server logs."
                return "I encountered an unexpected error. Please try again."

    # ------------------------------------------------------------------
    # Internal routing
    # ------------------------------------------------------------------

    async def _predict_intent(self, query: str) -> tuple[str, str | None]:
        """Return (intent_type, tool_name_or_None) using the semantic router.
        
        Override checks fire FIRST so keyword shortcuts (factual queries, sandbox
        requests) always win regardless of what the semantic router predicted.
        This prevents the router returning 'calculate' for 'Who is X?' style queries.
        """
        lower_query = query.lower().strip()

        # ── Priority 0: Identity exclusion (Prevents "Who are you" -> web search) ──
        _IDENTITY_PHRASES = [
            "who are you", "what are you", "your name", "who am i talking to",
            "what's your name", "tell me about yourself", "who made you",
            "who created you", "your creator",
        ]
        if any(p in lower_query for p in _IDENTITY_PHRASES):
            logger.info("Triage override: Identity query detected, routing to conversational")
            return "conversational", None

        # ── Priority 0.5: URL Detection (Shared links -> fetch_webpage_content) ──
        url_match = re.search(r"https?://[^\s]+", lower_query)
        if url_match:
            logger.info("Triage override: URL detected, routing to fetch_webpage_content")
            return "tool", "fetch_webpage_content"

        # ── Priority 1: Factual knowledge override ──────────────────────────
        _WIKI_PREFIXES = [
            "who is", "who was", "who are", "who were",
            "what is", "what was", "what are", "what were",
            "where is", "where was", "when did", "when was",
            "tell me about", "who created", "who invented",
            "who founded", "who wrote",
        ]
        _LIVE_PREFIXES = ["who won", "how many", "current score", "what happened"]

        # Exception: Weather should go to get_weather, not wikipedia/web
        if "weather" in lower_query or "temperature" in lower_query:
            pass
        elif "news" in lower_query or "headlines" in lower_query:
            logger.info("Triage override: News query detected, routing to get_news")
            return "tool", "get_news"
        elif any(lower_query.startswith(p) for p in _LIVE_PREFIXES):
            logger.info("Triage override: Live query detected, routing to web_search")
            return "tool", "web_search"
        elif any(lower_query.startswith(p) for p in _WIKI_PREFIXES):
            logger.info("Triage override: Factual query detected, routing to wikipedia_search")
            return "tool", "wikipedia_search"

        # ── Priority 1.2: Sandbox execution override ──────────────────────────
        # Strong coding intent → always use execute_python_script.
        _SANDBOX_TRIGGERS = [
            "write and run", "write a python", "run python", "execute python",
            "run a script", "execute a script", "write a script",
            "write code and run", "compute with python", "calculate using python",
            "run this code", "execute this code", "create a python", "create a script",
            "generate python", "generate a script",
        ]
        if any(t in lower_query for t in _SANDBOX_TRIGGERS):
            logger.info("Triage override: Sandbox execution request detected, routing to execute_python_script")
            return "tool", "execute_python_script"

        # ── Priority 1.3: App termination override ────────────────────────────
        # "close X", "kill X", "stop X", "terminate X" → always terminate_program.
        # The semantic router sometimes misses these short commands.
        _TERMINATE_VERBS = ["close ", "kill ", "stop ", "terminate ", "end ", "quit ", "exit "]
        _OPEN_VERBS = ["open ", "launch ", "start ", "run "]  # Exclude: "start recording" etc.
        if any(lower_query.startswith(v) for v in _TERMINATE_VERBS):
            logger.info("Triage override: App close/kill detected, routing to terminate_program")
            return "tool", "terminate_program"
        # Also catch mid-sentence patterns: "please close chrome", "can you kill vlc"
        _TERMINATE_PATTERNS = [
            "please close ", "please kill ", "please stop ", "please terminate ",
            "can you close ", "can you kill ", "can you stop ",
            "force close ", "force quit ", "force kill ",
            "shut down ", "shutdown ",
        ]
        if any(p in lower_query for p in _TERMINATE_PATTERNS):
            logger.info("Triage override: App close pattern detected, routing to terminate_program")
            return "tool", "terminate_program"

        # ── Priority 1.4: App open override ────────────────────────────────
        # Mirror of the terminate override for opening apps.
        if any(lower_query.startswith(v) for v in _OPEN_VERBS):
            logger.info("Triage override: App open detected, routing to open_program")
            return "tool", "open_program"

        # ── Priority 1.5: Content Generation Detection ─────────────────────
        if self._is_content_generation(lower_query):
            logger.info("Triage override: Content generation detected, routing to content_generation")
            return "content_generation", None

        # ── Default: semantic router ────────────────────────────────────────
        if self._semantic_router.is_ready:
            intent_type, tool_name = self._semantic_router.route(query)
        else:
            intent_type, tool_name = "conversational", None

        return intent_type, tool_name

    def _is_content_generation(self, lower_query: str) -> bool:
        """Return True if the query asks to write/create long-form content."""
        verbs = ["write", "compose", "create", "draft", "generate", "explain in detail"]
        nouns = [
            "essay", "article", "story", "poem", "code", "script", "program",
            "letter", "email", "report", "summary", "paragraph", "post", "blog"
        ]
        return any(v in lower_query for v in verbs) and any(n in lower_query for n in nouns)

    async def _process_command_internal(
        self,
        user_input: str,
        conversation_manager: ConversationManager,
        context: RequestContext,
    ) -> tuple[str, str | None]:
        """Single-step triage → extract → dispatch → compose pipeline.

        MoE integration: 'expert' intents are routed through the MoE graph
        so the Supervisor can activate the correct specialized expert.
        """
        intent_type, target_name = await self._predict_intent(user_input)

        if intent_type == "cloud_escalation":
            logger.info("Triage: cloud escalation detected")
            response = await self._composer.compose_conversational(
                user_input=user_input,
                session_id=context.session_id,
                context_summary=conversation_manager.get_context_summary(),
                recent_history=conversation_manager.get_formatted_history(3),
                complexity="high",
            )
            return response, None

        if intent_type == "conversational":
            logger.info("Triage: conversational")
            response = await self._composer.compose_conversational(
                user_input=user_input,
                session_id=context.session_id,
                context_summary=conversation_manager.get_context_summary(),
                recent_history=conversation_manager.get_formatted_history(3),
            )
            return response, None

        if intent_type == "content_generation":
            logger.info("Triage: content generation")
            response = await self._composer.compose_long_form(
                user_input=user_input,
                session_id=context.session_id,
                context_summary=conversation_manager.get_context_summary(),
                recent_history=conversation_manager.get_formatted_history(3),
            )
            return response, None

        # ── MoE: Route 'expert' intents through the MoE graph ──────────
        if intent_type == "expert":
            logger.info("Triage: MoE expert=%s", target_name)
            response, tools_used = await self._process_with_agent(
                user_input,
                conversation_manager=conversation_manager,
                context=context,
                routing_intent="expert",
                routing_target=target_name or "",
            )
            tool_used = ", ".join(tools_used) if tools_used else None
            return response, tool_used

        # ── intent_type == "tool" — direct single-tool dispatch ─────────
        actual_tool_name = target_name or ""
        logger.info("Triage: tool=%s", actual_tool_name)

        if self.tool_registry.get(actual_tool_name):
            args = await self._arg_extractor.extract(actual_tool_name, user_input)
            result = await self._tool_dispatcher.dispatch(
                actual_tool_name, args, context
            )
            if result.success:
                if actual_tool_name == "fetch_webpage_content":
                    # Specialized summary for webpage content
                    prose = await self._composer.compose_tool_response(
                        user_input,
                        actual_tool_name,
                        result.output,
                        instruction="Summarize the content of the webpage provided below. Be thorough but concise."
                    )
                else:
                    prose = await self._composer.compose_tool_response(
                        user_input, actual_tool_name, result.output
                    )
                return prose, actual_tool_name
            # P8: Don't return raw error strings directly to the user.
            error_prose = await self._composer.compose_tool_response(
                user_input,
                actual_tool_name,
                f"The tool reported an error: {result.output}",
            )
            return error_prose, actual_tool_name

        if getattr(self, "client", None) and not self.settings.LOCAL_ONLY_MODE:
            return await self._process_with_gemini(
                user_input,
                [actual_tool_name],
                conversation_manager=conversation_manager,
                context=context,
            )

        return "I couldn't find the right tool for that. Try rephrasing your request.", None

    # ------------------------------------------------------------------
    # Multi-step / agent delegation
    # ------------------------------------------------------------------

    def _is_multi_step_query(self, user_input: str) -> bool:
        """Return True only when the query clearly requires chaining 2+ distinct tools.

        Tightened to avoid routing single-tool queries that contain 'and' (e.g.
        'Who is X and what did he do?') to the heavier LangGraph agent.
        Requires both a conjunction indicator AND evidence of 2 distinct tool categories.
        """
        lower = user_input.lower()

        # Must contain an explicit chaining conjunction
        multi_indicators = [" then ", " after that ", " also ", " and then ", " as well as "]
        if not any(ind in lower for ind in multi_indicators):
            return False

        # Only trigger when we can clearly identify 2+ distinct tool-category intents
        intent_keyword_groups = [
            ["time", "date", "what day", "current time"],
            ["weather", "temperature", "forecast"],
            ["joke", "make me laugh", "funny"],
            ["my tasks", "my todo", "list tasks"],
            ["my notes", "list notes"],
            ["reminder", "remind me"],
            ["system", "cpu usage", "memory usage", "disk usage"],
            ["news", "headlines"],
            ["battery"],
            ["email", "inbox"],
            ["pomodoro", "timer"],
        ]
        matched = sum(1 for kws in intent_keyword_groups if any(k in lower for k in kws))
        return matched >= 2

    async def _process_with_agent(
        self,
        user_input: str,
        conversation_manager: ConversationManager,
        context: RequestContext,
        routing_intent: str = "conversational",
        routing_target: str = "",
    ) -> tuple[str, list[str]]:
        """Delegate to the MoE LangGraph agent with routing context."""
        context_summary = conversation_manager.get_context_summary()
        result = await self.graph.ainvoke(
            task=user_input,
            context=context,
            context_summary=context_summary,
            routing_intent=routing_intent,
            routing_target=routing_target,
        )
        if result.success:
            logger.info(
                "MoE agent completed: expert=%s, tools=%s",
                result.expert_used, result.tools_used,
            )
            return result.final_answer, result.tools_used
        return result.error or "I couldn't complete that task.", []

    async def handle_background_event(self, event_prompt: str, context: RequestContext) -> None:
        """Process a background/proactive event silently via the agent loop."""
        try:
            manager = await self._get_conversation_manager(context.session_id)
            _response, tools_used = await self._process_with_agent(
                event_prompt, conversation_manager=manager, context=context
            )
            logger.info("Background event processed. Tools used: %s", tools_used)
        except Exception:
            logger.exception("Error handling background event")

    # ------------------------------------------------------------------
    # Gemini direct call (LOCAL_ONLY_MODE blocks this path)
    # ------------------------------------------------------------------

    async def _process_with_gemini(
        self,
        user_input: str,
        relevant_tools: list[str],
        conversation_manager: ConversationManager,
        context: RequestContext,
    ) -> tuple[str, str | None]:
        """Last-resort Gemini call. Only reached when LOCAL_ONLY_MODE is False."""
        from google.genai import types

        system_prompt = await self._composer.build_system_prompt(
            session_id=context.session_id,
            context_summary=conversation_manager.get_context_summary(),
            user_query=user_input,
        )
        tools_config = self.tool_registry.build_gemini_tools(relevant_tools)

        if self.cache_service:
            cached = await self.cache_service.get_llm(user_input, "gemini")
            if cached:
                logger.info("LLM cache hit (%d chars)", len(user_input))
                return cached, None

        try:
            if self.client is None or self.settings.LOCAL_ONLY_MODE:
                raise ValueError("Gemini client unavailable or LOCAL_ONLY_MODE active")

            config = types.GenerateContentConfig(
                tools=tools_config if tools_config else None,
            )
            # PC-01: Gemini SDK is synchronous; run it in a thread pool so we
            # never block the asyncio event loop during inference (1-10 seconds).
            loop = asyncio.get_running_loop()
            _client = self.client
            _model = self.model_name
            gemini_response = await loop.run_in_executor(
                None,
                lambda: _client.models.generate_content(
                    model=_model,
                    contents=system_prompt + "\n\n" + user_input,
                    config=config,
                ),
            )

            if gemini_response.function_calls:
                fc = gemini_response.function_calls[0]
                tool_name = fc.name or "unknown"
                args = dict(fc.args) if getattr(fc, "args", None) else {}
                result = await self._tool_dispatcher.dispatch(tool_name, args, context)
                prose = await self._composer.compose_tool_response(
                    user_input, tool_name, result.output
                )
                return prose, tool_name

            direct = (
                gemini_response.text
                if hasattr(gemini_response, "text") and gemini_response.text
                else str(gemini_response)
            )
            if self.cache_service:
                await self.cache_service.set_llm(user_input, direct, "gemini")
            self._bump_gemini_metric()
            return direct, None

        except Exception as exc:
            logger.exception("Gemini API error: %s", repr(exc))
            return f"I had trouble processing that: {exc}", None

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def get_tool_summary(self) -> dict[str, object]:
        return self.tool_registry.get_summary()

    async def clear_conversation(self, session_id: str) -> None:
        manager = await self._get_conversation_manager(session_id)
        await manager.clear()
        await self.memory_service.clear_session(session_id)

    async def shutdown(self) -> None:
        if hasattr(self, "graph"):
            await self.graph.shutdown()
        # Close the async SQLite checkpointer cleanly.
        if self._checkpointer_cm is not None:
            try:
                await self._checkpointer_cm.__aexit__(None, None, None)
            except Exception:
                logger.warning("Error closing AsyncSqliteSaver", exc_info=True)
            finally:
                self._checkpointer_cm = None
                self._checkpointer = None

    async def send_outbound_message(self, user_id: str, platform: str, message: str) -> bool:
        try:
            logger.info("Preparing outbound %s message to %s...", platform, user_id)
            manager = await self._get_conversation_manager(user_id)
            await manager.add(
                "assistant", message, metadata={"outbound": True, "platform": platform}
            )
            return await self.messaging.send_message(user_id, message, platform=platform)
        except Exception:
            logger.error(
                "Failed to send outbound message to %s on %s", user_id, platform, exc_info=True
            )
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_conversation_manager(self, session_id: str) -> ConversationManager:
        manager = ConversationManager(session_id=session_id, repo=self._conversation_repo)
        await manager.load_from_db()
        return manager

    def _load_api_keys(self) -> None:
        if not self.settings.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not found — Gemini features disabled")
            self.client = None
            self.model_name = self.settings.GEMINI_MODEL
            return
        # Lazy import: google.genai costs ~62MB RSS — only load it when a
        # Gemini key is actually configured.
        from google import genai

        self.client = genai.Client(api_key=self.settings.GEMINI_API_KEY)
        self.model_name = self.settings.GEMINI_MODEL
        logger.info("Gemini API configured with model: %s", self.model_name)

    def _make_llm_generate(self) -> Callable[..., Awaitable[str]] | None:
        """Build an async LLM generate closure for the LangGraph agent."""
        if getattr(self, "llm_router", None) is None and not (hasattr(self, "client") and self.client):
            return None

        async def _generate(prompt: str, **kwargs: Any) -> str:
            structured = kwargs.get("structured", False)
            complexity = kwargs.get("complexity", "high")

            router = getattr(self, "llm_router", None)
            if router is not None:
                response, _ = await router.generate(
                    prompt, complexity=complexity, structured=structured
                )
                return response

            loop = asyncio.get_running_loop()
            if self.client is None or self.settings.LOCAL_ONLY_MODE:
                raise ValueError("Gemini client unavailable and no LLMRouter configured.")

            # Simple fallback for Gemini if router is missing
            response = await loop.run_in_executor(
                None,
                lambda: self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt + ("\n\nIMPORTANT: Respond ONLY with a valid JSON object." if structured else ""),
                ),
            )
            return str(response.text) if hasattr(response, "text") else str(response)

        return _generate

    @staticmethod
    def _bump_gemini_metric() -> None:
        try:
            from src.infra.metrics import amadeus_llm_calls_total
            amadeus_llm_calls_total.labels(provider="gemini").inc()
        except Exception:
            pass
