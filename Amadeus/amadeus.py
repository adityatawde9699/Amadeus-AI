
import os
import sys
import json
import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Optional
from dataclasses import dataclass, field
from enum import Enum
from dotenv import load_dotenv
from functools import wraps
import inspect

if sys.platform.startswith('win'):
    import io
    # Use getattr to avoid static type checker errors if 'reconfigure' is not present,
    # and fall back to wrapping the underlying buffer with a TextIOWrapper.
    reconfig_out = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfig_out):
        reconfig_out(encoding='utf-8')
    else:
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        except Exception:
            pass

    reconfig_err = getattr(sys.stderr, "reconfigure", None)
    if callable(reconfig_err):
        reconfig_err(encoding='utf-8')
    else:
        try:
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
        except Exception:
            pass

import google.generativeai as genai

# Local imports
from general_utils import *
from system_controls import *
from system_monitor import *
from task_utils import *
from note_utils import *
from reminder_utils import ReminderManager
from speech_utils import speak, recognize_speech
from memory_utils import load_memory, save_memory, update_memory
from db import init_db_async

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        # Explicitly set encoding='utf-8' to prevent crashes on Hindi/Russian text
        logging.FileHandler('amadeus.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('Amadeus')


class ToolCategory(Enum):
    """Categories for organizing tools."""
    SYSTEM = "system"
    PRODUCTIVITY = "productivity"
    INFORMATION = "information"
    COMMUNICATION = "communication"


@dataclass
class Tool:
    """Enhanced tool definition with metadata."""
    name: str
    function: Callable
    description: str
    category: ToolCategory
    parameters: dict = field(default_factory=dict)
    requires_confirmation: bool = False
    is_async: bool = False

    def __post_init__(self):
        # Auto-detect if function is async
        self.is_async = asyncio.iscoroutinefunction(self.function)


@dataclass
class ConversationMessage:
    """Structured conversation message."""
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    tool_used: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class ConversationManager:
    """Manages conversation history with context window optimization."""
    
    def __init__(self, max_messages: int = 20, max_tokens_estimate: int = 4000):
        self.messages: list[ConversationMessage] = []
        self.max_messages = max_messages
        self.max_tokens_estimate = max_tokens_estimate
    
    def add(self, role: str, content: str, tool_used: Optional[str] = None, **metadata):
        """Add a message to the conversation history."""
        msg = ConversationMessage(
            role=role, content=content, tool_used=tool_used, metadata=metadata
        )
        self.messages.append(msg)
        self._trim_history()
    
    def _trim_history(self):
        """Trim history to stay within limits while preserving context."""
        # Keep recent messages and important ones (tool usage, errors)
        if len(self.messages) > self.max_messages:
            # Always keep first 2 (context) and last N messages
            important = [m for m in self.messages[2:-10] if m.tool_used]
            self.messages = self.messages[:2] + important[-3:] + self.messages[-10:]
    
    def get_formatted_history(self, last_n: int = 10) -> str:
        """Get formatted conversation history for the AI prompt."""
        recent = self.messages[-last_n:] if len(self.messages) > last_n else self.messages
        formatted = []
        for msg in recent:
            prefix = "User" if msg.role == "user" else "Amadeus"
            tool_info = f" [used: {msg.tool_used}]" if msg.tool_used else ""
            formatted.append(f"{prefix}{tool_info}: {msg.content}")
        return "\n".join(formatted)
    
    def get_context_summary(self) -> str:
        """Generate a brief summary of the conversation context."""
        if not self.messages:
            return "No prior conversation."
        
        tools_used = [m.tool_used for m in self.messages if m.tool_used]
        topics = set()
        for m in self.messages[-5:]:
            # Simple topic extraction
            words = m.content.lower().split()
            for kw in ['weather', 'news', 'task', 'reminder', 'note', 'file', 'time']:
                if kw in words:
                    topics.add(kw)
        
        return f"Recent topics: {', '.join(topics) or 'general'}. Tools used: {', '.join(set(tools_used[-3:])) or 'none'}."
    
    def clear(self):
        """Clear conversation history."""
        self.messages.clear()


class ToolExecutor:
    """Handles safe execution of tools with error handling and retries."""
    
    def __init__(self, max_retries: int = 2):
        self.max_retries = max_retries
        self.execution_history: list[dict] = []
    
    async def execute(self, tool: Tool, args: dict) -> tuple[bool, Any]:
        """Execute a tool with proper error handling and async support."""
        for attempt in range(self.max_retries + 1):
            try:
                logger.info(f"Executing tool '{tool.name}' with args: {args} (attempt {attempt + 1})")
                
                # Validate arguments against expected parameters
                validated_args = self._validate_args(tool, args)
                
                # Execute based on async or sync
                if tool.is_async:
                    result = await tool.function(**validated_args)
                else:
                    # Run sync functions in executor to not block
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, lambda: tool.function(**validated_args))
                
                # Log successful execution
                self.execution_history.append({
                    'tool': tool.name, 'args': args, 'success': True,
                    'timestamp': datetime.now().isoformat()
                })
                
                return True, result
                
            except TypeError as e:
                logger.warning(f"Argument error for {tool.name}: {e}")
                if attempt == self.max_retries:
                    return False, f"Invalid arguments for {tool.name}: {e}"
            except Exception as e:
                logger.error(f"Tool execution error ({tool.name}): {e}", exc_info=True)
                if attempt == self.max_retries:
                    self.execution_history.append({
                        'tool': tool.name, 'args': args, 'success': False,
                        'error': str(e), 'timestamp': datetime.now().isoformat()
                    })
                    return False, f"Error executing {tool.name}: {e}"
                await asyncio.sleep(0.5)  # Brief delay before retry
        
        return False, "Max retries exceeded"
    
    def _validate_args(self, tool: Tool, args: dict) -> dict:
        """Validate and clean arguments for a tool."""
        sig = inspect.signature(tool.function)
        valid_params = set(sig.parameters.keys())
        
        # Filter to only valid parameters
        cleaned = {k: v for k, v in args.items() if k in valid_params}
        
        # Check for required parameters
        for name, param in sig.parameters.items():
            if param.default == inspect.Parameter.empty and name not in cleaned:
                if name not in ('self', 'cls'):
                    logger.warning(f"Missing required parameter '{name}' for {tool.name}")
        
        return cleaned


class Amadeus:
    """Enhanced Amadeus AI Assistant with improved architecture."""
    
    def __init__(self, debug_mode: bool = False, voice_enabled: bool = True):
        self.debug_mode = debug_mode
        self.voice_enabled = voice_enabled and not debug_mode
        self.running = False
        
        # Core components
        self.conversation = ConversationManager()
        self.tool_executor = ToolExecutor()
        self.reminder_manager = ReminderManager()
        
        # Identity and behavior configuration
        self.config = {
            'name': 'Amadeus',
            'personality': 'helpful, concise, and friendly',
            'default_location': 'India',
            'timezone': 'Asia/Kolkata'
        }
        
        self.identity_prompt = self._build_identity_prompt()
        
        # Initialize
        self._load_api_keys()
        self.tools = self._register_tools()
        load_memory()
        
        logger.info(f"Amadeus initialized with {len(self.tools)} tools")
    def _build_identity_prompt(self) -> str:
        """Build a comprehensive identity prompt with advanced context awareness."""
        time_context = self._get_time_context()
        system_context = self._get_system_context()
        
        return f"""You are {self.config['name']}, an intelligent AI assistant with advanced capabilities.

    Personality: {self.config['personality']}
    Current time: {{current_time}}
    System Status: {system_context}
    User context: {{context_summary}}
    Conversation Mode: {self._get_conversation_mode()}

    Guidelines:
    - Be concise, natural, and contextually aware in responses
    - Don't introduce yourself unless asked
    - When using tools, explain what you're doing briefly
    - If a task fails, suggest alternatives and retry strategies
    - Remember and build upon context from the conversation
    - Adapt tone based on task urgency and user needs
    - Provide proactive suggestions when relevant

    Available tool categories: System, Productivity, Information, Communication

    Interaction Preferences:
    - Response style: {self.config.get('response_style', 'balanced')}
    - Verbosity level: {self.config.get('verbosity', 'concise')}
    - Proactive assistance: {self.config.get('proactive_mode', True)}"""

    def _get_time_context(self) -> str:
        """Generate contextual time information."""
        now = datetime.now()
        hour = now.hour
        
        if 5 <= hour < 12:
            period = "morning"
        elif 12 <= hour < 17:
            period = "afternoon"
        elif 17 <= hour < 21:
            period = "evening"
        else:
            period = "night"
        
        return f"({period}, {now.strftime('%H:%M')})"

    def _get_system_context(self) -> str:
        """Get current system health context."""
        try:
            cpu = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory().percent
            return f"CPU: {cpu}%, Memory: {memory}%"
        except Exception:
            return "System monitoring unavailable"

    def _get_conversation_mode(self) -> str:
        """Determine current conversation mode."""
        recent_tools = [m.tool_used for m in self.conversation.messages[-5:] if m.tool_used]
        if not recent_tools:
            return "Conversational"
        elif len(set(recent_tools)) >= 2:
            return "Task-oriented"
        else:
            return "Information-gathering"

    def _load_api_keys(self):
        """Load and validate API keys with enhanced error handling."""
        load_dotenv()
        
        required_keys = ["GEMINI_API_KEY"]
        optional_keys = ["NEWS_API_KEY", "WEATHER_API_KEY"]
        
        missing_required = []
        for key in required_keys:
            if not os.getenv(key):
                missing_required.append(key)
        
        if missing_required:
            raise ValueError(f"Missing required API keys: {', '.join(missing_required)}")
        
        for key in optional_keys:
            if os.getenv(key):
                logger.info(f"Optional API key '{key}' configured")
            else:
                logger.warning(f"Optional API key '{key}' not configured")
        
        logger.info("API keys validated successfully")
        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key:
            raise ValueError("GEMINI_API_KEY not found in .env file")
        
        genai.configure(api_key=gemini_key) # type: ignore
        
        # Use a more capable model with better JSON output
        self.model = genai.GenerativeModel( 'gemini-2.0-flash') #type: ignore
        logger.info("Gemini API configured successfully")
    
    def _register_tools(self) -> dict[str, Tool]:
        """Register all available tools with enhanced metadata."""
        tools = {}
        
        # System Tools
        system_tools = [
            Tool("get_datetime_info", get_datetime_info,
                 "Gets current date, time, or day. Args: query (str)",
                 ToolCategory.SYSTEM, {'query': 'str'}),
            Tool("system_status", generate_system_summary,
                 "Provides system status (CPU, memory, disk)",
                 ToolCategory.SYSTEM),
            Tool("open_program", open_program,
                 "Opens an application. Args: app_name (str)",
                 ToolCategory.SYSTEM, {'app_name': 'str'}),
            Tool("search_file", search_file,
                 "Searches for files. Args: file_name (str), search_directory (optional)",
                 ToolCategory.SYSTEM, {'file_name': 'str'}),
             # --- NEW: Open Websites ---
            Tool("open_website", open_website,
                 "Opens a website or performs a Google search. Args: query (str - url or search term)",
                 ToolCategory.SYSTEM, {'query': 'str'}),
        ]
        
        # Information Tools
        info_tools = [
            Tool("get_news", get_news_async,  
                 "Fetches top news headlines from India",
                 ToolCategory.INFORMATION),
            Tool("get_weather", get_weather_async, 
                 "Gets weather for a location. Args: location (str, default: India)",
                 ToolCategory.INFORMATION, {'location': 'str'}),
             # --- NEW: Wikipedia ---
            Tool("wikipedia_search", wikipedia_search,
                 "Searches Wikipedia for a summary. Args: query (str)",
                 ToolCategory.INFORMATION, {'query': 'str'}),
        ]

        # Communication / Fun Tools
        comm_tools = [
            # --- NEW: Jokes ---
            Tool("tell_joke", tell_joke,
                 "Tells a random joke.",
                 ToolCategory.COMMUNICATION),
        ]
        
        # Task Management Tools
        task_tools = [
            Tool("add_task", add_task,
                 "Adds a new task. Args: task_content (str)",
                 ToolCategory.PRODUCTIVITY, {'task_content': 'str'}),
            Tool("list_tasks", list_tasks,
                 "Lists tasks. Optional: status_filter ('pending'/'completed')",
                 ToolCategory.PRODUCTIVITY),
            Tool("complete_task", complete_task,
                 "Marks task complete. Args: identifier (ID or content)",
                 ToolCategory.PRODUCTIVITY, {'identifier': 'str'}),
            Tool("delete_task", delete_task,
                 "Deletes a task. Args: identifier (ID or content)",
                 ToolCategory.PRODUCTIVITY, {'identifier': 'str'}, requires_confirmation=True),
            Tool("get_task_summary", get_task_summary,
                 "Gets summary of all tasks",
                 ToolCategory.PRODUCTIVITY),
        ]
        
        # Note Tools
        note_tools = [
            Tool("create_note", create_note,
                 "Creates a note. Args: title, content, tags (optional list)",
                 ToolCategory.PRODUCTIVITY, {'title': 'str', 'content': 'str'}),
            Tool("list_notes", list_notes,
                 "Lists notes. Optional: tag filter",
                 ToolCategory.PRODUCTIVITY),
            Tool("get_note", get_note,
                 "Gets full note content. Args: note_id (int)",
                 ToolCategory.PRODUCTIVITY, {'note_id': 'int'}),
            Tool("update_note", update_note,
                 "Updates a note. Args: note_id, title/content/tags (optional)",
                 ToolCategory.PRODUCTIVITY, {'note_id': 'int'}),
            Tool("delete_note", delete_note,
                 "Deletes a note. Args: note_id (int)",
                 ToolCategory.PRODUCTIVITY, {'note_id': 'int'}, requires_confirmation=True),
            Tool("get_notes_summary", get_notes_summary,
                 "Gets summary of all notes",
                 ToolCategory.PRODUCTIVITY),
        ]
        
        # Reminder Tools
        reminder_tools = [
            Tool("add_reminder", self.reminder_manager.add_reminder,
                 "Sets a reminder. Args: title, time_str (e.g., 'tomorrow at 5pm'), description (optional)",
                 ToolCategory.PRODUCTIVITY, {'title': 'str', 'time_str': 'str'}),
            Tool("list_reminders", self.reminder_manager.list_reminders,
                 "Lists all active reminders",
                 ToolCategory.PRODUCTIVITY),
            Tool("delete_reminder", self.reminder_manager.delete_reminder,
                 "Deletes a reminder. Args: reminder_id (int)",
                 ToolCategory.PRODUCTIVITY, {'reminder_id': 'int'}),
        ]
        
        # Register all tools
        # Added comm_tools to this list
        for tool_list in [system_tools, info_tools, comm_tools, task_tools, note_tools, reminder_tools]:
            for tool in tool_list:
                tools[tool.name] = tool
        
        return tools
    
    def _get_tool_descriptions(self) -> str:
        """Generate formatted tool descriptions for the AI prompt."""
        by_category = {}
        for tool in self.tools.values():
            cat = tool.category.value
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(f"  - `{tool.name}`: {tool.description}")
        
        sections = []
        for cat, tools in by_category.items():
            sections.append(f"**{cat.title()}:**\n" + "\n".join(tools))
        
        return "\n\n".join(sections)
    
    async def _select_tool(self, command: str) -> tuple[Optional[str], dict]:
        """Use AI to select the appropriate tool for a command."""
        tool_descriptions = self._get_tool_descriptions()
        
        selection_prompt = f"""Analyze this user command and select the best tool.

User command: "{command}"

Available tools:
{tool_descriptions}

Respond ONLY with a JSON object (no markdown, no backticks):
{{"tool": "tool_name_or_conversational", "args": {{"param": "value"}}, "confidence": 0.0-1.0}}

If no tool fits, use: {{"tool": "conversational", "args": {{}}, "confidence": 1.0}}

Examples:
- "what time is it" -> {{"tool": "get_datetime_info", "args": {{"query": "time"}}, "confidence": 0.95}}
- "add task buy groceries" -> {{"tool": "add_task", "args": {{"task_content": "buy groceries"}}, "confidence": 0.9}}
- "how are you" -> {{"tool": "conversational", "args": {{}}, "confidence": 1.0}}
"""
        
        try:
            response = await asyncio.to_thread(
                self.model.generate_content, selection_prompt
            )
            
            text = self._extract_response_text(response)
            if not text:
                logger.warning("Empty response from tool selection")
                return None, {}
            
            # Clean and parse JSON
            cleaned = text.strip()
            # Remove markdown code blocks if present
            if cleaned.startswith('```'):
                cleaned = cleaned.split('\n', 1)[-1].rsplit('```', 1)[0]
            cleaned = cleaned.replace('`', '').replace('json', '').strip()
            
            choice = json.loads(cleaned)
            
            tool_name = choice.get('tool')
            args = choice.get('args', {})
            confidence = choice.get('confidence', 0.5)
            
            logger.info(f"Tool selection: {tool_name} (confidence: {confidence})")
            
            # If confidence is low, might want conversational fallback
            if confidence < 0.3 and tool_name != 'conversational':
                logger.info("Low confidence, falling back to conversational")
                return 'conversational', {}
            
            return tool_name, args
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error in tool selection: {e}")
            return 'conversational', {}
        except Exception as e:
            logger.error(f"Tool selection error: {e}", exc_info=True)
            return None, {}
    
    def _extract_response_text(self, response) -> Optional[str]:
        """Robustly extract text from various Gemini response formats."""
        # Direct text attribute
        if hasattr(response, 'text') and response.text:
            return response.text
        
        # Try candidates
        candidates = getattr(response, 'candidates', None)
        if candidates and len(candidates) > 0:
            candidate = candidates[0]
            # Try content.parts
            content = getattr(candidate, 'content', None)
            if content:
                parts = getattr(content, 'parts', None)
                if parts and len(parts) > 0:
                    return getattr(parts[0], 'text', str(parts[0]))
            # Direct text on candidate
            if hasattr(candidate, 'text'):
                return candidate.text
        
        # Dict-like access
        if isinstance(response, dict):
            if 'text' in response:
                return response['text']
            if 'candidates' in response:
                return response['candidates'][0].get('content', '')
        
        return None
    
    def _format_tool_result(self, result: Any) -> str:
        """Format tool execution result into a speakable string."""
        if result is None:
            return "Done."
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            if 'message' in result:
                return str(result['message'])
            if 'status' in result and 'data' in result:
                return f"{result['status']}: {result['data']}"
            return json.dumps(result, indent=2)
        if isinstance(result, (list, tuple)):
            if all(isinstance(x, str) for x in result):
                return "\n".join(result)
            return "\n".join(str(x) for x in result)
        return str(result)
    
    async def _conversational_reply(self, prompt: str) -> str:
        """Generate a conversational reply using the AI model."""
        context = self.identity_prompt.format(
            current_time=datetime.now().strftime('%I:%M %p on %A, %B %d'),
            context_summary=self.conversation.get_context_summary()
        )
        
        history = self.conversation.get_formatted_history(last_n=8)
        
        full_prompt = f"""{context}

Recent conversation:
{history}

User: {prompt}
{self.config['name']}:"""
        
        try:
            response = await asyncio.to_thread(
                self.model.generate_content, full_prompt
            )
            
            reply = self._extract_response_text(response)
            if not reply:
                reply = "I'm not sure how to respond to that."
            
            # Update conversation and memory
            self.conversation.add('user', prompt)
            self.conversation.add('assistant', reply)
            update_memory(prompt, reply)
            
            return reply.strip()
            
        except Exception as e:
            logger.error(f"Conversational reply error: {e}", exc_info=True)
            return "I'm having trouble processing that right now."
    
    async def process_command(self, command: str) -> str:
        """Process a user command with improved async handling."""
        if not command or not command.strip():
            return "I didn't catch that. Could you repeat?"
        
        command = command.strip()
        logger.info(f"Processing command: {command[:50]}...")
        
        # Select appropriate tool
        tool_name, args = await self._select_tool(command)
        
        if tool_name is None:
            return "I encountered an error processing your request."
        
        if tool_name == 'conversational':
            return await self._conversational_reply(command)
        
        if tool_name not in self.tools:
            logger.warning(f"Unknown tool selected: {tool_name}")
            return await self._conversational_reply(command)
        
        tool = self.tools[tool_name]
        
        # Handle confirmation for dangerous operations
        if tool.requires_confirmation and not self.debug_mode:
            speak(f"Are you sure you want to {tool_name.replace('_', ' ')}? Say yes to confirm.")
            confirmation = recognize_speech()
            if not confirmation or 'yes' not in confirmation.lower():
                return "Operation cancelled."
        
        # Execute the tool
        success, result = await self.tool_executor.execute(tool, args)
        
        if success:
            formatted = self._format_tool_result(result)
            self.conversation.add('user', command, tool_used=tool_name)
            self.conversation.add('assistant', formatted, tool_used=tool_name)
            return formatted
        else:
            # Tool failed, try conversational fallback
            logger.warning(f"Tool {tool_name} failed: {result}")
            return f"I couldn't complete that action. {result}"
    
    async def generate_daily_brief(self) -> str:
        """Generate a comprehensive daily briefing with improved error handling."""
        now = datetime.now()
        parts = [f"{get_greeting()}!"]
        parts.append(f"It's {now.strftime('%I:%M %p')} on {now.strftime('%A, %B %d')}.")
        
        # Tasks - with better error handling and formatting
        try:
            task_summary = get_task_summary()
            if task_summary and isinstance(task_summary, str) and task_summary.strip():
                parts.append(task_summary)
            else:
                logger.debug("No task summary available")
        except Exception as e:
            logger.warning(f"Could not get task summary: {e}", exc_info=False)
            parts.append("Tasks: Unable to retrieve summary.")
        
        # Reminders - with validation
        try:
            reminders = self.reminder_manager.list_reminders()
            if reminders:
                reminder_count = len(reminders)
                reminder_text = f"You have {reminder_count} active reminder{'s' if reminder_count != 1 else ''}."
                parts.append(reminder_text)
            else:
                parts.append("No active reminders.")
        except Exception as e:
            logger.warning(f"Could not get reminders: {e}", exc_info=False)
            parts.append("Reminders: Unable to retrieve.")
        
        # Weather - with validation and error recovery
        try:
            weather = await get_weather_async(self.config.get('default_location', 'India')) # <--- CHANGED
            if weather and isinstance(weather, str):
                if "Sorry" not in weather and "error" not in weather.lower():
                    parts.append(weather)
                else:
                    logger.info("Weather service unavailable or returned error")
            else:
                logger.debug("Weather data unavailable or invalid format")
        except Exception as e:
            logger.warning(f"Could not get weather: {e}", exc_info=False)
        
        # Join with better spacing
        brief = " ".join(parts)
        if not brief or brief.count(" ") < 10:
            logger.warning("Daily brief is too short, may be incomplete")
        
        return brief
    
    def _speak(self, text: str, priority: str = "normal"):
        """Speak text synchronously.
        CRITICAL FIX: Running this on the main thread prevents pyttsx3 freezing."""
        if not text or not text.strip():
            return
        
        # Skip redundant outputs
        if hasattr(self, '_last_spoken') and self._last_spoken == text:
            logger.debug("Skipping duplicate speech output")
            return
        
        self._last_spoken = text
        
        # Print first so we see output even if voice fails
        print(f"[{self.config['name']}]: {text}")

        if self.voice_enabled:
            try:
                # Run directly (Synchronously) - Do NOT use asyncio.to_thread here
                speak(text)
            except Exception as e:
                logger.error(f"Speech synthesis failed: {e}")

    async def _listen(self) -> Optional[str]:
        """Get input with timeout and validation.
        CRITICAL FIX: Made async to await results without starting a new loop."""
        if self.debug_mode:
            try:
                # Run input in a thread so it doesn't block the async loop
                return await asyncio.to_thread(input, "> ")
            except EOFError:
                return None
        else:
            try:
                print("\n🎤 Listening...")
                # DIRECT AWAIT - No asyncio.run()
                result = await asyncio.wait_for(
                    asyncio.to_thread(recognize_speech), 
                    timeout=10.0
                )
                return result.strip() if result else None
            except asyncio.TimeoutError:
                logger.warning("Speech recognition timeout")
                return None
            except Exception as e:
                logger.error(f"Speech recognition error: {e}")
                return None

    async def _main_loop(self):
        """Enhanced main loop with better state management."""
        logger.info("Initializing database...")
        await init_db_async()
        
        # Show daily brief on startup
        try:
            brief = await self.generate_daily_brief()
            self._speak(brief)  # Sync call
        except Exception as e:
            logger.warning(f"Could not generate daily brief: {e}")
        
        exit_commands = {'exit', 'goodbye', 'quit', 'bye', 'stop', 'sleep'}
        consecutive_failures = 0
        max_failures = 3
        
        while self.running:
            try:
                # AWAIT the async listen method
                command = await self._listen()
                
                if command is None:
                    consecutive_failures += 1
                    if consecutive_failures >= max_failures:
                        self._speak("I'm having trouble hearing you. Please check your microphone.")
                        consecutive_failures = 0
                    continue
                
                consecutive_failures = 0  # Reset on successful input
                
                # Check exit commands
                if any(ec in command.lower() for ec in exit_commands):
                    self._speak("Shutting down. Goodbye!")
                    self.running = False
                    break
                
                # Process with timeout
                try:
                    response = await asyncio.wait_for(
                        self.process_command(command),
                        timeout=30.0
                    )
                    self._speak(response) # Sync call
                except asyncio.TimeoutError:
                    self._speak("That operation took too long. Please try again.")
                    logger.warning(f"Command timeout: {command[:50]}")
                
            except Exception as e:
                logger.error(f"Main loop error: {e}", exc_info=True)
                self._speak("An error occurred. Trying to continue...")

    def start(self):
        """Start with enhanced initialization and error recovery."""
        self.running = True
        self.reminder_manager.start_monitoring()
        
        greeting = f"{get_greeting()}! {self.config['name']} is online and ready."
        self._speak(greeting) # Sync call
        
        try:
            asyncio.run(self._main_loop())
        except KeyboardInterrupt:
            logger.info("Interrupted by user (Ctrl+C)")
            self._speak("Shutting down...")
        except Exception as e:
            logger.critical(f"Fatal error: {e}", exc_info=True)
            print(f"Fatal error: {e}")
        finally:
            self.shutdown()

    def shutdown(self):
        """Enhanced shutdown with resource cleanup."""
        self.running = False
        
        try:
            self.reminder_manager.stop_monitoring()
            save_memory()
            logger.info("Amadeus shutdown complete")
            print("✓ Amadeus shutdown complete.")
        except Exception as e:
            logger.error(f"Shutdown error: {e}", exc_info=True)
    
    
    # Enhanced entry point with better CLI
    if __name__ == "__main__":
        import argparse
        
        parser = argparse.ArgumentParser(
            description="Amadeus AI Assistant",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
    Examples:
      python amadeus.py              # Run normally with voice
      python amadeus.py --debug      # Text-only debug mode
      python amadeus.py --brief      # Show daily brief and exit
            """
        )
        parser.add_argument('--debug', '-d', action='store_true', 
                           help='Run in debug/text mode (no voice)')
        parser.add_argument('--brief', '-b', action='store_true', 
                           help='Show daily briefing and exit')
        parser.add_argument('--no-voice', action='store_true',
                           help='Disable voice output but run normally')
        parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                           default='INFO', help='Set logging level')
        
        args = parser.parse_args()
        
        # Configure logging
        logging.getLogger('Amadeus').setLevel(getattr(logging, args.log_level))
        
        # Initialize assistant
        assistant = Amadeus( # pyright: ignore[reportUndefinedVariable]
            debug_mode=args.debug,
            voice_enabled=not (args.debug or args.no_voice)
        )
        
        if args.brief:
            brief = asyncio.run(assistant.generate_daily_brief())
            print(brief)
        else:
            assistant.start()