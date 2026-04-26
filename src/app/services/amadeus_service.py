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
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from google import genai

from src.app.services.argument_extractor import ArgumentExtractor
from src.app.services.conversation_manager import ConversationManager, IConversationRepository
from src.app.services.response_composer import ResponseComposer
from src.app.services.semantic_router import UnifiedSemanticRouter
from src.app.services.tool_dispatcher import ToolDispatcher
from src.app.services.tool_registry import ToolRegistry
from src.core.config import Settings, get_settings
from src.core.domain.models import PermissionProfile
from src.infra.knowledge_graph import KnowledgeGraphService
from src.infra.memory_service import QdrantMemoryService
from src.infra.messaging.telegram_adapter import TelegramAdapter
from src.infra.messaging.whatsapp_adapter import WhatsAppAdapter
from src.infra.tools.base import ToolExecutor


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
      3. Route: multi-step → AgentOrchestrator, single-step → sub-services.
      4. Persist conversation turns and long-term memories.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        tool_registry: ToolRegistry | None = None,
        conversation_repo: IConversationRepository | None = None,
        session_id: str | None = None,
        debug_mode: bool = False,
        cache_service: CacheService | None = None,
        auto_start_orchestrator: bool = True,
        llm_router: LLMRouter | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.debug_mode = debug_mode
        self.cache_service = cache_service
        self.session_id = session_id or str(uuid.uuid4())
        self.client: genai.Client | None = None
        self.model_name: str = self.settings.GEMINI_MODEL
        self._conversation_repo = conversation_repo
        self._conversation_managers: dict[str, ConversationManager] = {}

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

        # ── Conversation Manager ──────────────────────────────────────
        self.conversation_manager = ConversationManager(
            session_id=self.session_id,
            repo=conversation_repo,
        )
        self._conversation_managers[self.session_id] = self.conversation_manager

        # ── Long-term Memory (Qdrant + KG) ────────────────────────────
        self.memory_service = QdrantMemoryService(settings=self.settings)
        self.kg_service = KnowledgeGraphService()

        if self.memory_service.is_enabled:
            logger.info("Tiered memory system ENABLED — Qdrant + KG ready")
        else:
            logger.info("Long-term memory DISABLED — operating with session-only context")

        # ── Gemini direct client (LOCAL_ONLY_MODE blocks actual calls) ─
        self._load_api_keys()

        # ── Semantic Router ───────────────────────────────────────────
        self._semantic_router = UnifiedSemanticRouter(
            registry=self.tool_registry,
            model_dir=self.settings.BASE_DIR / "Model",
            threshold=0.38,
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
            kg_service=self.kg_service,
        )

        # ── Agent Orchestrator (multi-step) ───────────────────────────
        from src.app.services.agent_loop import AgentOrchestrator

        llm_generate = self._make_llm_generate()
        self.orchestrator = AgentOrchestrator(
            tool_registry=self.tool_registry,
            tool_executor=self.tool_executor,
            llm_generate=llm_generate,
            auto_start=auto_start_orchestrator,
        )

        logger.info(
            "AmadeusService initialized — %d tools, session=%s...",
            len(self.tool_registry),
            self.session_id[:8],
        )

    # ------------------------------------------------------------------
    # Async initialization
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Async startup: warm memory service and hydrate conversation cache from DB."""
        await self.memory_service.initialize()
        await self.conversation_manager.load_from_db()
        if not self._semantic_router.is_ready:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._semantic_router.build_index)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def handle_command(
        self,
        user_input: str,
        source: str = "text",
        request_id: str | None = None,
        session_id: str | None = None,
        permission_profile: PermissionProfile = PermissionProfile.SYSTEM_FULL,
    ) -> str:
        """
        Main entry point. Returns the assistant's response as a string.

        ``session_id`` is passed per call so singleton service instances are
        safe under concurrent requests.
        """
        if not user_input.strip():
            return "I didn't catch that. Could you repeat?"

        active_session_id = session_id or self.session_id
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
                    permission_profile=permission_profile,
                )
                tool_used = ", ".join(tools_used) if tools_used else None
            else:
                response, tool_used = await self._process_command_internal(
                    user_input,
                    session_id=active_session_id,
                    conversation_manager=conversation_manager,
                    permission_profile=permission_profile,
                )

            await conversation_manager.add("assistant", response, tool_used=tool_used)
            await self.memory_service.store(
                active_session_id, "assistant", response, subtype="interaction", importance=0.4
            )
            return response

        except Exception as exc:
            from src.app.services.agent_loop import QueueFullError

            if isinstance(exc, QueueFullError):
                raise

            logger.error("Error handling command: %s", exc, exc_info=True)
            if self.debug_mode or getattr(self.settings, "ALLOW_DEBUG_RESPONSES", False):
                return f"I encountered an error ({type(exc).__name__}). Check the server logs."
            return "I encountered an unexpected error. Please try again."

    # ------------------------------------------------------------------
    # Internal routing
    # ------------------------------------------------------------------

    async def _predict_intent(self, query: str) -> tuple[str, str | None]:
        """Return (intent_type, tool_name_or_None) using the semantic router."""
        if self._semantic_router.is_ready:
            return self._semantic_router.route(query)
        return "conversational", None

    async def _process_command_internal(
        self,
        user_input: str,
        session_id: str,
        conversation_manager: ConversationManager,
        permission_profile: PermissionProfile = PermissionProfile.SYSTEM_FULL,
    ) -> tuple[str, str | None]:
        """Single-step triage → extract → dispatch → compose pipeline."""
        intent_type, tool_name = await self._predict_intent(user_input)

        if intent_type == "cloud_escalation":
            logger.info("Triage: cloud escalation detected")
            response = await self._composer.compose_conversational(
                user_input=user_input,
                session_id=session_id,
                context_summary=conversation_manager.get_context_summary(),
                recent_history=conversation_manager.get_formatted_history(3),
                complexity="high",
            )
            return response, None

        if intent_type == "conversational":
            logger.info("Triage: conversational")
            response = await self._composer.compose_conversational(
                user_input=user_input,
                session_id=session_id,
                context_summary=conversation_manager.get_context_summary(),
                recent_history=conversation_manager.get_formatted_history(3),
            )
            return response, None

        # intent_type == "tool"
        actual_tool_name = tool_name or ""
        logger.info("Triage: tool=%s", actual_tool_name)

        if self.tool_registry.get(actual_tool_name):
            args = await self._arg_extractor.extract(actual_tool_name, user_input)
            result = await self._tool_dispatcher.dispatch(
                actual_tool_name, args, permission_profile
            )
            if result.success:
                prose = await self._composer.compose_tool_response(
                    user_input, actual_tool_name, result.output
                )
                return prose, actual_tool_name
            return result.output, actual_tool_name

        # Tool not in registry — Gemini last-resort (blocked in LOCAL_ONLY_MODE)
        if getattr(self, "client", None) and not self.settings.LOCAL_ONLY_MODE:
            return await self._process_with_gemini(
                user_input,
                [actual_tool_name],
                session_id=session_id,
                conversation_manager=conversation_manager,
                permission_profile=permission_profile,
            )

        return "I couldn't find the right tool for that. Try rephrasing your request.", None

    # ------------------------------------------------------------------
    # Multi-step / agent delegation
    # ------------------------------------------------------------------

    def _is_multi_step_query(self, user_input: str) -> bool:
        lower = user_input.lower()
        multi_indicators = [" and ", " then ", " also ", " plus ", " as well as "]
        if not any(ind in lower for ind in multi_indicators):
            return False
        intent_keywords = [
            ["time", "date", "day"], ["weather", "temperature"], ["joke", "funny"],
            ["task", "todo"], ["note"], ["reminder"], ["system", "cpu", "memory"],
            ["news"], ["battery"],
        ]
        return sum(1 for kws in intent_keywords if any(k in lower for k in kws)) >= 2

    async def _process_with_agent(
        self,
        user_input: str,
        conversation_manager: ConversationManager,
        permission_profile: PermissionProfile = PermissionProfile.SYSTEM_FULL,
    ) -> tuple[str, list[str]]:
        context = conversation_manager.get_context_summary()
        result = await self.orchestrator.execute(
            task=user_input, context=context, permission_profile=permission_profile
        )
        if result.success:
            return result.final_answer, result.tools_used
        return result.error or "I couldn't complete that task.", []

    async def handle_background_event(self, event_prompt: str) -> None:
        """Process a background/proactive event silently via the agent loop."""
        try:
            manager = await self._get_conversation_manager(self.session_id)
            _response, tools_used = await self._process_with_agent(
                event_prompt, conversation_manager=manager
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
        session_id: str,
        conversation_manager: ConversationManager,
        permission_profile: PermissionProfile = PermissionProfile.SYSTEM_FULL,
    ) -> tuple[str, str | None]:
        """Last-resort Gemini call. Only reached when LOCAL_ONLY_MODE is False."""
        from google.genai import types

        system_prompt = await self._composer.build_system_prompt(
            session_id=session_id,
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
            gemini_response = self.client.models.generate_content(
                model=self.model_name,
                contents=system_prompt + "\n\n" + user_input,
                config=config,
            )

            if gemini_response.function_calls:
                fc = gemini_response.function_calls[0]
                tool_name = fc.name or "unknown"
                args = dict(fc.args) if getattr(fc, "args", None) else {}
                result = await self._tool_dispatcher.dispatch(tool_name, args, permission_profile)
                prose = await self._composer.compose_tool_response(
                    user_input, tool_name, result.output
                )
                return prose, tool_name

            direct = (
                str(gemini_response.text)
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

    async def clear_conversation(self, session_id: str | None = None) -> None:
        active_session_id = session_id or self.session_id
        manager = await self._get_conversation_manager(active_session_id)
        await manager.clear()
        await self.memory_service.clear_session(active_session_id)

    async def shutdown(self) -> None:
        if hasattr(self, "orchestrator"):
            await self.orchestrator.shutdown()

    async def send_outbound_message(self, user_id: str, platform: str, message: str) -> bool:
        try:
            logger.info("Preparing outbound %s message to %s...", platform, user_id)
            manager = await self._get_conversation_manager(user_id)
            await manager.add(
                "assistant", message, metadata={"outbound": True, "platform": platform}
            )
            if platform.lower() == "telegram":
                adapter = TelegramAdapter()
                await adapter.send_message(int(user_id), message)
                return True
            if platform.lower() == "whatsapp":
                wa_adapter = WhatsAppAdapter()
                await wa_adapter.send_message(user_id, message)
                return True
            logger.error("Unsupported outbound platform: %s", platform)
            return False
        except Exception:
            logger.error(
                "Failed to send outbound message to %s on %s", user_id, platform, exc_info=True
            )
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_conversation_manager(self, session_id: str) -> ConversationManager:
        manager = self._conversation_managers.get(session_id)
        if manager is None:
            manager = ConversationManager(session_id=session_id, repo=self._conversation_repo)
            self._conversation_managers[session_id] = manager
        await manager.load_from_db()
        return manager

    def _load_api_keys(self) -> None:
        if not self.settings.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not found — Gemini features disabled")
            self.client = None
            self.model_name = self.settings.GEMINI_MODEL
            return
        self.client = genai.Client(api_key=self.settings.GEMINI_API_KEY)
        self.model_name = self.settings.GEMINI_MODEL
        logger.info("Gemini API configured with model: %s", self.model_name)

    def _make_llm_generate(self) -> Callable[[str], Awaitable[str]] | None:
        """Build an async Gemini generate closure for the AgentOrchestrator."""
        if not (hasattr(self, "client") and self.client):
            return None

        async def _generate(prompt: str) -> str:
            loop = asyncio.get_running_loop()
            if self.client is None or self.settings.LOCAL_ONLY_MODE:
                raise ValueError("Gemini client unavailable")
            response = await loop.run_in_executor(
                None,
                lambda: self.client.models.generate_content(  # type: ignore[union-attr]
                    model=self.model_name,
                    contents=prompt,
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
