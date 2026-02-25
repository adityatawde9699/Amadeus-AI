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
import os
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.infra.cache.cache_service import CacheService

import google.generativeai as genai
import joblib
import numpy as np

from src.core.config import Settings, get_settings
from src.app.services.tool_registry import ToolRegistry
from src.infra.tools.base import Tool, ToolCategory, ToolExecutor
from src.infra.memory_service import QdrantMemoryService
from src.infra.messaging.telegram_adapter import TelegramAdapter
from src.infra.messaging.whatsapp_adapter import WhatsAppAdapter


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
        self,
        role: str,
        content: str,
        tool_used: str | None = None,
        **metadata: Any
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
                    timestamp=datetime.fromisoformat(m["timestamp"]) if m.get("timestamp") else datetime.now(),
                )
                for m in messages
            ]
            self._cache_loaded = True
            logger.info(f"Loaded {len(self._cache)} messages from DB for session {self.session_id[:8]}...")
        except Exception as e:
            logger.error(f"Failed to load conversation history: {e}")
    
    def _trim_cache(self) -> None:
        """Keep cache within limits."""
        if len(self._cache) > self.max_context:
            # Keep recent messages with important ones (tool usage)
            important = [m for m in self._cache[:-10] if m.tool_used]
            self._cache = important[-3:] + self._cache[-10:]
    
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
            for kw in ['weather', 'news', 'task', 'reminder', 'note', 'file', 'time', 'system']:
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
    ):
        self.settings = settings or get_settings()
        self.debug_mode = debug_mode
        self.cache_service = cache_service
        
        # Session management
        import uuid
        self.session_id = session_id or str(uuid.uuid4())
        
        # UNIFIED conversation manager (uses DB as source of truth)
        self.conversation_manager = ConversationManager(
            session_id=self.session_id,
            repo=conversation_repo,
        )
        
        self.tool_executor = ToolExecutor()
        self.tool_registry = tool_registry or ToolRegistry()

        # Long-term semantic memory (ChromaDB + Gemini embeddings)
        self.memory_service = QdrantMemoryService(settings=self.settings)
        if self.memory_service.is_enabled:
            logger.info("Long-term memory ENABLED — ChromaDB ready (%d stored memories)", self.memory_service.memory_count)
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
        llm_generate = None
        if self.model:
            def _generate(prompt: str) -> str:
                response = self.model.generate_content(prompt)
                return response.text if hasattr(response, "text") else str(response)
            llm_generate = _generate

        self.orchestrator = AgentOrchestrator(
            tool_registry=self.tool_registry,
            tool_executor=self.tool_executor,
            llm_generate=llm_generate
        )
        
        logger.info(f"AmadeusService initialized with {len(self.tool_registry)} tools, session={self.session_id[:8]}...")
    
    async def initialize(self) -> None:
        """Async initialization - load conversation history from DB."""
        await self.conversation_manager.load_from_db()
    
    # =========================================================================
    # INITIALIZATION
    # =========================================================================
    
    def _load_api_keys(self) -> None:
        """Load and configure API keys."""
        if not self.settings.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not found - AI features will be limited")
            self.model = None
            return
        
        genai.configure(api_key=self.settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(self.settings.GEMINI_MODEL)
        logger.info(f"Gemini API configured with model: {self.settings.GEMINI_MODEL}")
    
    def _load_tool_classifier(self) -> None:
        """
        Load TF-IDF vectorizer and SVM classifier for smart tool selection.
        
        This is the key quota-saving feature: predict relevant tools locally
        instead of sending all tools to Gemini with every request.
        """
        try:
            vectorizer_path = "Model/tfidf_vectorizer.joblib"
            classifier_path = "Model/svm_classifier.joblib"
            
            if os.path.exists(vectorizer_path) and os.path.exists(classifier_path):
                self.vectorizer = joblib.load(vectorizer_path)
                self.classifier = joblib.load(classifier_path)
                self.classifier_enabled = True
                logger.info("Tool classifier models loaded. Smart tool selection ENABLED.")
            else:
                logger.warning("Tool classifier models not found. Using all-tools mode.")
                self.classifier_enabled = False
        except Exception as e:
            logger.error(f"Failed to load tool classifier: {e}")
            self.classifier_enabled = False
    
    def _register_all_tools(self) -> None:
        """Register all tools from the tool modules."""
        # Import and register tools from each module
        try:
            from src.infra.tools.info_tools import get_info_tools
            from src.infra.tools.system_tools import get_system_tools
            from src.infra.tools.monitor_tools import get_monitor_tools
            from src.infra.tools.productivity_tools import get_productivity_tools
            from src.infra.tools.agent_tools import get_agent_tools
            
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
            
            logger.info(f"Registered {len(self.tool_registry)} tools from modules")
        except Exception as e:
            logger.error(f"Error registering tools: {e}")
    
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
            X = self.vectorizer.transform([query])
            
            # Get scores from SVM
            scores = self.classifier.decision_function(X)[0]
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
            logger.error(f"Error predicting tools: {e}. Fallback to all.")
            return self.tool_registry.list_names()
    
    # =========================================================================
    # COMMAND PROCESSING
    # =========================================================================
    
    async def handle_command(
        self,
        user_input: str,
        source: str = "text",
        request_id: str | None = None,
    ) -> str:
        """
        Main entry point for processing user commands.
        
        Args:
            user_input: The user's input text
            source: Source of input (voice, text, api)
            request_id: Optional request ID for tracing
            
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
                response, tools_used = await self._process_with_agent(user_input)
                tool_used = ", ".join(tools_used) if tools_used else None
            else:
                # Single-step processing
                response, tool_used = await self._process_command_internal(user_input)
            
            # Add assistant response (unified - goes to both cache and DB)
            await self.conversation_manager.add("assistant", response, tool_used=tool_used)

            # Store assistant response in long-term semantic memory
            await self.memory_service.store(self.session_id, "assistant", response)

            return response
            
        except Exception as e:
            logger.error(f"Error handling command: {e}", exc_info=True)
            if self.debug_mode or self.settings.DEBUG:
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
    
    async def _process_with_agent(self, user_input: str) -> tuple[str, list[str]]:
        """
        Process a multi-step query using the Agent Orchestrator.
        """
        context = self.conversation_manager.get_context_summary()
        
        # Submit task to the background Orchestrator queue
        result = await self.orchestrator.execute(task=user_input, context=context)
        
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
            response, tools_used = await self._process_with_agent(event_prompt)
            # The agent executes tools. If it uses schedule_future_task or send_outbound_message, 
            # they are executed within _process_with_agent.
            logger.info(f"Background event processed. Tools used: {tools_used}")
        except Exception as e:
            logger.error(f"Error handling background event: {e}")
    
    
    async def _process_command_internal(self, user_input: str) -> tuple[str, str | None]:
        """
        Internal command processing with ML-powered tool selection.
        
        Flow:
        1. Predict relevant tools using ML classifier
        2. If conversational, respond without tools
        3. Otherwise, call Gemini with relevant tools only
        4. Execute any function calls
        5. Return final response
        
        Returns:
            Tuple of (response_text, tool_used_name or None)
        """
        # Check if Gemini is available
        if self.model is None:
            # Without Gemini, try to execute tools directly based on keywords
            return await self._process_without_gemini(user_input)
        
        # Step 1: Predict relevant tools
        relevant_tools = self._predict_relevant_tools(user_input)
        
        # Step 2: Check for conversational intent
        if relevant_tools == ["conversational"]:
            response = await self._generate_conversational_response(user_input)
            return (response, None)
        
        # Step 3: Build prompt with context
        current_time = datetime.now().strftime("%I:%M %p on %A, %B %d")
        context_summary = self.conversation_manager.get_context_summary()

        # Retrieve semantically relevant long-term memories
        long_term_memories = await self.memory_service.retrieve(user_input, top_k=5)
        memory_context = self.memory_service.format_for_prompt(long_term_memories)

        system_prompt = self.identity_prompt.format(
            current_time=current_time,
            session_id=self.session_id,
            context_summary=context_summary,
        )
        if memory_context:
            system_prompt = f"{system_prompt}\n\n{memory_context}"

        # Step 4: Get Gemini declarations for relevant tools only
        tools_config = self.tool_registry.build_gemini_tools(relevant_tools)
        
        # Check LLM cache BEFORE calling Gemini
        if self.cache_service:
            cached_llm = await self.cache_service.get_llm(user_input, "gemini")
            if cached_llm:
                logger.info("LLM cache hit (%d chars)", len(user_input))
                # Update cache hit rate gauge
                try:
                    from src.api.server import amadeus_cache_hit_rate
                    stats = self.cache_service.get_stats()
                    amadeus_cache_hit_rate.set(stats["hit_rate_pct"])
                except Exception:
                    pass
                return (cached_llm, None)

                
        # Step 5: Call Gemini
        try:
            response = self.model.generate_content(
                [system_prompt, user_input],
                tools=tools_config,
            )
            
            # Step 6: Check for function calls
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        tool_name = part.function_call.name
                        # Execute the function call
                        result = await self._execute_function_call(part.function_call)
                        
                        # Generate a response incorporating the result
                        final_response = await self._generate_response_with_result(
                            user_input, tool_name, result
                        )
                        return (final_response, tool_name)
            
            # No function call - return text response
            text = response.text if hasattr(response, "text") else str(response)

            # Increment Prometheus LLM call counter (conversational, no tool)
            try:
                from src.api.server import amadeus_llm_calls_total
                amadeus_llm_calls_total.labels(provider="gemini").inc()
            except Exception:
                pass

            if self.cache_service:
                await self.cache_service.set_llm(user_input, text, "gemini")
            return (text, None)

            
        except Exception as e:
            logger.error("Gemini API error type: %s", type(e).__name__)
            logger.error("Gemini API error: %s", repr(e))
            import traceback
            logger.error("Traceback: %s", traceback.format_exc())
            return (f"I had trouble processing that: {e}", None)

    
    async def _process_without_gemini(self, user_input: str) -> tuple[str, str | None]:
        """Fallback processing when Gemini is not available."""
        lower_input = user_input.lower()
        
        # Time-related queries
        if any(kw in lower_input for kw in ["time", "date", "day"]):
            tool = self.tool_registry.get("get_datetime_info")
            if tool:
                result = await self.tool_executor.execute(tool, {"query": user_input})
                if result.success:
                    return (result.result, "get_datetime_info")
                return ("Could not get time info.", None)
        
        # System status
        if any(kw in lower_input for kw in ["system", "cpu", "memory", "status"]):
            tool = self.tool_registry.get("system_status")
            if tool:
                result = await self.tool_executor.execute(tool, {})
                if result.success:
                    return (result.result, "system_status")
                return ("Could not get system status.", None)
        
        # Task listing
        if "task" in lower_input and any(kw in lower_input for kw in ["list", "show", "what"]):
            tool = self.tool_registry.get("list_tasks")
            if tool:
                result = await self.tool_executor.execute(tool, {})
                if result.success:
                    return (result.result, "list_tasks")
                return ("Could not list tasks.", None)
        
        return (
            "GEMINI_API_KEY is not configured. I can only perform basic commands. "
            "Set the GEMINI_API_KEY in your .env file for full AI capabilities.",
            None
        )
    
    async def _execute_function_call(self, function_call: Any) -> str:
        """Execute a Gemini function call."""
        tool_name = function_call.name
        args = dict(function_call.args) if function_call.args else {}
        
        # Increment Prometheus tool call counter
        try:
            from src.api.server import amadeus_tool_calls_total
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
                    from src.api.server import amadeus_cache_hit_rate
                    stats = self.cache_service.get_stats()
                    amadeus_cache_hit_rate.set(stats["hit_rate_pct"])
                except Exception:
                    pass
                return cached_result

                
        tool = self.tool_registry.get(tool_name)
        if not tool:
            return f"Tool '{tool_name}' not found"
        
        result = await self.tool_executor.execute(tool, args)
        
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

        prompt = f"""{self.identity_prompt.format(
            current_time=current_time,
            session_id=self.session_id,
            context_summary=self.conversation_manager.get_context_summary(),
        )}
{memory_context}

Recent conversation:
{context}

User: {user_input}

Respond naturally and conversationally. Be concise."""

        try:
            response = self.model.generate_content(prompt)
            return response.text if hasattr(response, "text") else str(response)
        except Exception as e:
            logger.error(f"Error generating response: {e}")
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
            response = self.model.generate_content(prompt)
            return response.text if hasattr(response, "text") else result
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
        if hasattr(self, 'orchestrator'):
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
                role="assistant", 
                content=message, 
                metadata={"outbound": True, "platform": platform}
            )
            
            # Dispatch to the correct adapter
            platform_lower = platform.lower()
            if platform_lower == "telegram":
                adapter = TelegramAdapter(settings=self.settings)
                await adapter.send_message(user_id, message)
                return True
                
            elif platform_lower == "whatsapp":
                adapter = WhatsAppAdapter(settings=self.settings)
                await adapter.send_message(user_id, message)
                return True
                
            else:
                logger.error(f"Unsupported outbound platform: {platform}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send outbound message to {user_id} on {platform}: {e}", exc_info=True)
            return False

