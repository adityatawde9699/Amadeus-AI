"""
Service interfaces for Amadeus AI Assistant.

These abstract base classes define the contracts for core services.
Infrastructure implementations must adhere to these interfaces,
enabling dependency injection and easy swapping of implementations.

Usage:
    from src.core.interfaces.services import IVoiceInput, IVoiceOutput
    
    class WhisperVoiceInput(IVoiceInput):
        def listen(self) -> str:
            # Implementation using Whisper
            ...
"""

from abc import ABC, abstractmethod
from typing import Any

from src.core.domain.models import (
    ConversationContext,
    InteractionLog,
    SystemStatus,
    ToolDefinition,
    ToolExecutionResult,
)


# =============================================================================
# VOICE INTERFACES
# =============================================================================

class IVoiceInput(ABC):
    """Interface for speech-to-text services."""
    
    @abstractmethod
    def listen(
        self,
        timeout: int | None = None,
        phrase_time_limit: int | None = None
    ) -> str:
        """
        Listen to microphone and return transcribed text.
        
        Args:
            timeout: Maximum seconds to wait for speech to begin.
            phrase_time_limit: Maximum seconds for a single phrase.
            
        Returns:
            Transcribed text from speech, empty string if nothing heard.
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the voice input service is available."""
        pass


class IVoiceOutput(ABC):
    """Interface for text-to-speech services."""
    
    @abstractmethod
    def speak(self, text: str) -> None:
        """
        Synthesize text to speech.
        
        Args:
            text: The text to speak.
        """
        pass
    
    @abstractmethod
    def speak_async(self, text: str) -> None:
        """
        Synthesize text to speech asynchronously (non-blocking).
        
        Args:
            text: The text to speak.
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the voice output service is available."""
        pass


# =============================================================================
# AI/ML INTERFACES
# =============================================================================

class IIntentClassifier(ABC):
    """Interface for intent classification services."""
    
    @abstractmethod
    def predict_intent(self, text: str) -> str:
        """
        Determine what the user wants to do.
        
        Args:
            text: The user's input text.
            
        Returns:
            The predicted intent category/name.
        """
        pass
    
    @abstractmethod
    def get_confidence(self, text: str) -> tuple[str, float]:
        """
        Get intent prediction with confidence score.
        
        Args:
            text: The user's input text.
            
        Returns:
            Tuple of (intent, confidence_score).
        """
        pass


class ILLMService(ABC):
    """Interface for Large Language Model services."""
    
    @abstractmethod
    async def generate_response(
        self,
        prompt: str,
        context: ConversationContext | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """
        Generate a response using the LLM.
        
        Args:
            prompt: The user's input or prompt.
            context: Optional conversation context for continuity.
            temperature: Creativity parameter (0.0-1.0).
            max_tokens: Maximum tokens in response.
            
        Returns:
            The generated text response.
        """
        pass
    
    @abstractmethod
    async def generate_with_tools(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        context: ConversationContext | None = None,
    ) -> tuple[str | None, ToolExecutionResult | None]:
        """
        Generate a response with function calling capability.
        
        Args:
            prompt: The user's input.
            tools: Available tools the LLM can call.
            context: Optional conversation context.
            
        Returns:
            Tuple of (text_response, tool_result). One will be None.
        """
        pass


# =============================================================================
# MEMORY / PERSISTENCE INTERFACES  
# =============================================================================

class IMemoryService(ABC):
    """Interface for conversation memory and history services."""
    
    @abstractmethod
    def save_interaction(self, log: InteractionLog) -> None:
        """
        Persist an interaction to memory.
        
        Args:
            log: The interaction log to save.
        """
        pass
    
    @abstractmethod
    def retrieve_context(self, query: str, limit: int = 5) -> list[str]:
        """
        Retrieve relevant past interactions based on a query.
        
        Args:
            query: The search query.
            limit: Maximum number of results.
            
        Returns:
            List of relevant past interaction summaries.
        """
        pass
    
    @abstractmethod
    def get_recent_interactions(self, limit: int = 10) -> list[InteractionLog]:
        """
        Get the most recent interactions.
        
        Args:
            limit: Maximum number of interactions to return.
            
        Returns:
            List of recent interaction logs.
        """
        pass


# =============================================================================
# SYSTEM INTERFACES
# =============================================================================

class ISystemMonitor(ABC):
    """Interface for system monitoring services."""
    
    @abstractmethod
    def get_status(self) -> SystemStatus:
        """
        Get current system status.
        
        Returns:
            SystemStatus with CPU, memory, disk, battery info.
        """
        pass
    
    @abstractmethod
    def get_cpu_usage(self) -> float:
        """Get current CPU usage percentage."""
        pass
    
    @abstractmethod
    def get_memory_usage(self) -> float:
        """Get current memory usage percentage."""
        pass
    
    @abstractmethod
    def get_disk_usage(self, path: str = "/") -> float:
        """Get disk usage percentage for a path."""
        pass
    
    @abstractmethod
    def get_battery_info(self) -> tuple[float | None, bool]:
        """
        Get battery information.
        
        Returns:
            Tuple of (battery_percent, is_charging). Battery percent may be None
            if no battery is present.
        """
        pass


# =============================================================================
# TOOL EXECUTION INTERFACE
# =============================================================================

class IToolExecutor(ABC):
    """Interface for tool execution services."""
    
    @abstractmethod
    async def execute(
        self,
        tool_name: str,
        args: dict[str, Any],
    ) -> ToolExecutionResult:
        """
        Execute a tool with the given arguments.
        
        Args:
            tool_name: Name of the tool to execute.
            args: Arguments to pass to the tool.
            
        Returns:
            ToolExecutionResult with success status and result/error.
        """
        pass
    
    @abstractmethod
    def get_tool(self, name: str) -> ToolDefinition | None:
        """
        Get a tool definition by name.
        
        Args:
            name: The tool name.
            
        Returns:
            ToolDefinition if found, None otherwise.
        """
        pass
    
    @abstractmethod
    def list_tools(self, category: str | None = None) -> list[ToolDefinition]:
        """
        List available tools.
        
        Args:
            category: Optional category to filter by.
            
        Returns:
            List of tool definitions.
        """
        pass
