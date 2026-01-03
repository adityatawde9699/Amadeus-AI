
import os
import sys
import json
import asyncio
import logging
import psutil
from datetime import datetime
from typing import Any, Callable, Optional, Dict, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from dotenv import load_dotenv
from functools import wraps, partial
from functools import wraps, partial
import inspect
import joblib 
import numpy as np 

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
from general_utils import (
    get_greeting,
    get_datetime_info,
    get_weather_async,
    get_news_async,
    wikipedia_search_async,
    open_website,
    tell_joke,
    calculate,
    convert_temperature,
    convert_length,
    set_timer_async,
)
from system_controls import (
    open_program,
    search_file,
    read_file,
    copy_file,
    move_file,
    delete_file,
    create_folder,
    list_directory,
    terminate_program,
)
from system_monitor import (
    get_cpu_usage,
    get_memory_usage,
    get_disk_usage,
    get_battery_info,
    get_network_info,
    get_system_uptime,
    get_running_processes,
    get_any_gpu_stats,
    get_temperature_sensors,
    check_system_alerts,
    generate_system_summary,
    get_full_system_report,
)
from task_utils import (
    add_task,
    list_tasks,
    complete_task,
    delete_task,
    get_task_summary,
)
from note_utils import (
    create_note,
    list_notes,
    get_note,
    update_note,
    delete_note,
    get_notes_summary,
)
from reminder_utils import add_reminder, list_reminders, delete_reminder
from calendar_utils import (
    add_event,
    list_events,
    get_event,
    update_event,
    delete_event,
    get_today_agenda,
    get_upcoming_events,
    get_calendar_summary,
)
from pomodoro_utils import (
    start_pomodoro,
    stop_pomodoro,
    get_pomodoro_status,
    get_pomodoro_stats,
    start_break,
)
from speech_utils import recognize_speech
from memory_utils import load_memory, save_memory, update_memory
from db import init_db_async
from voice_service import VoiceService
from clock_service import ClockService
import config


# Configure logging
# Configure logging with Request ID support
class RequestIdFilter(logging.Filter):
    def filter(self, record):
        try:
            record.request_id = request_id_ctx.get()
        except LookupError:
            record.request_id = 'system'
        return True

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(request_id)s] - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('amadeus.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('Amadeus')
logger.addFilter(RequestIdFilter())


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
    
    def __init__(self, max_messages: Optional[int] = None, max_tokens_estimate: Optional[int] = None):
        self.messages: list[ConversationMessage] = []
        self.max_messages = max_messages or config.CONVERSATION_MAX_MESSAGES
        self.max_tokens_estimate = max_tokens_estimate or config.CONVERSATION_MAX_TOKENS_ESTIMATE
    
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
    
    def get_formatted_history(self, last_n: Optional[int] = None) -> str:
        """Get formatted conversation history for the AI prompt."""
        if last_n is None:
            last_n = config.CONVERSATION_HISTORY_LAST_N
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
    
    def __init__(self, max_retries: Optional[int] = None):
        self.max_retries = max_retries or config.TOOL_MAX_RETRIES
        self.execution_history: list[dict] = []
    
    async def execute(self, tool: Tool, args: Dict[str, Any]) -> Tuple[bool, Any]:
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
                    # Use functools.partial to properly capture arguments
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, partial(tool.function, **validated_args))
                
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
                await asyncio.sleep(config.TOOL_RETRY_DELAY)  # Brief delay before retry
        
        return False, "Max retries exceeded"
    
    def _validate_args(self, tool: Tool, args: Dict[str, Any]) -> Dict[str, Any]:
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


import contextvars

# Context variable for Request ID tracking
request_id_ctx = contextvars.ContextVar('request_id', default='system')

class Amadeus:
    """
    Enhanced Amadeus AI Assistant with Service-Oriented Architecture.
    
    Architecture:
    - Public API (Service Layer): handle_command, get_response
    - Internal Logic (Core): _process_command_internal, _select_tool
    - Infrastructure: database, memory, tools
    """
    
    def __init__(self, debug_mode: bool = False, voice_enabled: bool = True):
        self.debug_mode = debug_mode
        self.voice_enabled = voice_enabled and config.VOICE_ENABLED
        self.conversation_manager = ConversationManager()
        self.tool_executor = ToolExecutor()
        self.voice_service = VoiceService()
        self.voice_service.start()
        self.clock_service = ClockService(self.voice_service._queue)
        self.clock_service.start()
        
        # Service State
        self._is_running = False
        self._tasks: List[asyncio.Task] = []
        
        # Identity and behavior configuration
        self.config = config.get_assistant_config()
        self.identity_prompt = self._build_identity_prompt()
        
        # Initialize components
        self._load_api_keys()
        self.tools = self._register_tools()
        
        # --- INTELLIGENT TOOL SELECTION INITIALIZATION ---
        self._load_tool_classifier()
        
        load_memory()
        
        # Log configuration summary
        config.log_config_summary()
        logger.info(f"Amadeus initialized with {len(self.tools)} tools")

    def _load_tool_classifier(self):
        """Load TF-IDF vectorizer and SVM classifier for smart tool selection."""
        try:
            if os.path.exists(config.TOOL_VECTORIZER_PATH) and os.path.exists(config.TOOL_CLASSIFIER_PATH):
                self.vectorizer = joblib.load(config.TOOL_VECTORIZER_PATH)
                self.classifier = joblib.load(config.TOOL_CLASSIFIER_PATH)
                self.classifier_enabled = True
                logger.info("Tool classifier models loaded successfully. Intelligent tool selection ENABLED.")
            else:
                logger.warning("Tool classifier models not found. Using default (all tools) mode.")
                self.classifier_enabled = False
        except Exception as e:
            logger.error(f"Failed to load tool classifier: {e}", exc_info=True)
            self.classifier_enabled = False

    def _predict_relevant_tools(self, query: str, top_k: int = 3) -> List[str]:
        """
        Predict relevant tools using the loaded SVM model.
        Returns a list of tool names to be sent to Gemini.
        """
        if not self.classifier_enabled:
            return list(self.tools.keys())

        try:
            # Vectorize user query
            X = self.vectorizer.transform([query])
            
            # Get scores (decision_function returns distance to hyperplane)
            scores = self.classifier.decision_function(X)[0]
            classes = self.classifier.classes_
            
            # Sort by confidence (score) descending
            top_indices = np.argsort(scores)[::-1]
            
            # Get the single best prediction
            best_tool = classes[top_indices[0]]
            
            # Check for 'conversational' class
            if best_tool == 'conversational':
                logger.info("Classifier predicted 'conversational' - Skipping tool definitions.")
                return ["conversational"]
            
            # Get top K tools to provide redundancy/options
            top_tools = classes[top_indices[:top_k]]
            
            # Filter tools that actually exist in our registry
            relevant = [t for t in top_tools if t in self.tools]
            
            # If no relevant tools found (e.g. predictions were for deleted tools), fallback
            if not relevant:
                logger.warning(f"Classifier predicted {top_tools} but none exist. Fallback to all.")
                return list(self.tools.keys())
                
            logger.info(f"Smart Tool Selection: Selected {relevant} (Top: {best_tool})")
            return relevant

        except Exception as e:
            logger.error(f"Error predicting tools: {e}. Fallback to all tools.")
            return list(self.tools.keys())

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
        now = datetime.now()
        hour = now.hour
        if 5 <= hour < 12: period = "morning"
        elif 12 <= hour < 17: period = "afternoon"
        elif 17 <= hour < 21: period = "evening"
        else: period = "night"
        return f"({period}, {now.strftime('%H:%M')})"

    def _get_system_context(self) -> str:
        try:
            cpu = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory().percent
            return f"CPU: {cpu}%, Memory: {memory}%"
        except Exception:
            return "System monitoring unavailable"

    def _get_conversation_mode(self) -> str:
        recent_tools = [m.tool_used for m in self.conversation_manager.messages[-5:] if m.tool_used]
        if not recent_tools: return "Conversational"
        elif len(set(recent_tools)) >= 2: return "Task-oriented"
        else: return "Information-gathering"
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
        recent_tools = [m.tool_used for m in self.conversation_manager.messages[-5:] if m.tool_used]
        if not recent_tools:
            return "Conversational"
        elif len(set(recent_tools)) >= 2:
            return "Task-oriented"
        else:
            return "Information-gathering"

    def _load_api_keys(self):
        """Load and validate API keys with enhanced error handling."""
        if not config.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not found in .env file or environment variables")
        
        genai.configure(api_key=config.GEMINI_API_KEY) 
        
        if config.NEWS_API_KEY:
            logger.info("Optional API key 'NEWS_API_KEY' configured")
        else:
            logger.warning("Optional API key 'NEWS_API_KEY' not configured")
        
        if config.WEATHER_API_KEY:
            logger.info("Optional API key 'WEATHER_API_KEY' configured")
        else:
            logger.warning("Optional API key 'WEATHER_API_KEY' not configured")
        
        logger.info("API keys validated successfully")
        
        # Use configured model
        self.model = genai.GenerativeModel(config.GEMINI_MODEL) 
        logger.info("Gemini API configured successfully")
    
    def _register_tools(self) -> dict[str, Tool]:
        """Register all available tools with enhanced metadata."""
        tools = {}
        
        # Helper wrapper functions for better string output
        def wrap_bool_result(func, success_msg: str, fail_msg: str = "Operation failed."):
            """Wrap boolean-returning functions to return user-friendly strings."""
            def wrapper(*args, **kwargs):
                result = func(*args, **kwargs)
                if result:
                    return success_msg if success_msg else "Operation completed successfully."
                return fail_msg
            return wrapper
        
        def format_memory_usage():
            """Format memory usage as string."""
            mem = get_memory_usage()
            if mem:
                return f"Memory: {mem['used_gb']} GB / {mem['total_gb']} GB ({mem['percent']:.1f}% used)"
            return "Memory information unavailable."
        
        def format_disk_usage(path: str = "/"):
            """Format disk usage as string."""
            disk = get_disk_usage(path)
            if disk:
                return f"Disk: {disk['used_gb']} GB / {disk['total_gb']} GB ({disk['percent']:.1f}% used, {disk['free_gb']} GB free)"
            return "Disk information unavailable."
        
        def format_cpu_usage():
            """Format CPU usage as string."""
            cpu = get_cpu_usage()
            if cpu is not None:
                return f"CPU usage: {cpu:.1f}%"
            return "CPU information unavailable."
        
        def format_battery_info():
            """Format battery info as string."""
            battery = get_battery_info()
            if isinstance(battery, dict):
                return f"Battery: {battery['percent']}% - {battery['status']}" + (f" ({battery['time_left']})" if battery.get('time_left') != 'N/A' else "")
            return str(battery) if battery else "Battery information unavailable."
        
        def format_network_info():
            """Format network info as string."""
            net = get_network_info()
            if net:
                return f"Network: Sent {net['bytes_sent_mb']:.1f} MB, Received {net['bytes_recv_mb']:.1f} MB"
            return "Network information unavailable."
        
        def format_system_uptime():
            """Format system uptime as string."""
            uptime = get_system_uptime()
            if uptime:
                return f"System uptime: {uptime['uptime_str']} (since {uptime['boot_time']})"
            return "Uptime information unavailable."
        
        def format_running_processes(count: int = 10):
            """Format running processes as string."""
            processes = get_running_processes(count)
            if processes:
                result = f"Top {len(processes)} processes by memory:\n"
                for i, proc in enumerate(processes[:config.DISPLAY_PROCESSES_VOICE_COUNT], 1):
                    result += f"{i}. {proc['name']} (PID: {proc['pid']}, Memory: {proc['memory_percent']:.1f}%)\n"
                return result.strip()
            return "No process information available."
        
        def format_gpu_stats():
            """Format GPU stats as string."""
            gpu = get_any_gpu_stats()
            if isinstance(gpu, list) and gpu:
                result = f"GPU Information:\n"
                for g in gpu:
                    result += f"{g['name']}: {g['load']:.1f}% load, {g['memory_percent']:.1f}% memory, {g['temperature']}°C\n"
                return result.strip()
            return str(gpu) if gpu else "GPU information unavailable."
        
        def format_temperature_sensors():
            """Format temperature sensors as string."""
            temps = get_temperature_sensors()
            if isinstance(temps, dict) and temps:
                result = "Temperature Sensors:\n"
                for chip, sensors in list(temps.items())[:config.DISPLAY_TEMPERATURE_SENSORS_LIMIT]:
                    for sensor in sensors[:2]:  # Show 2 sensors per chip
                        result += f"{chip} {sensor['label']}: {sensor['current']}°C\n"
                return result.strip()
            return str(temps) if temps else "Temperature information unavailable."
        
        def format_system_alerts():
            """Format system alerts as string."""
            alerts = check_system_alerts(speak_alerts=False)
            if alerts:
                result = f"System Alerts ({len(alerts)}):\n"
                for alert in alerts[:config.DISPLAY_ALERTS_LIMIT]:
                    result += f"- {alert['message']}\n"
                return result.strip()
            return "No system alerts."
        
        def format_terminate_program(process_name: str = None, app_name: str = None, program_name: str = None, **kwargs) -> str:
            """Format terminate program result."""
            target_process = process_name or app_name or program_name or kwargs.get('name')
            if not target_process:
                return "Error: No process name provided."
            
            count = terminate_program(target_process)
            if count > 0:
                return f"Terminated {count} process(es) matching '{target_process}'"
            return f"No processes found matching '{target_process}'"

        def format_open_program(app_name: str = None, program_name: str = None, **kwargs) -> str:
            """Helper to make open_program return a string."""
            target_app = app_name or program_name or kwargs.get('name')
            if not target_app:
                return "Error: No application name provided."
            
            if open_program(target_app):
                return f"Opening {target_app}..."
            return f"Failed to open {target_app}."
        
        # --- 1. SYSTEM TOOLS (Hardware, OS, Files) ---
        # --- NEW ROBUST WRAPPERS ---
        def format_search_file(file_name: str = None, name: str = None, query: str = None, **kwargs) -> str:
            target = file_name or name or query or kwargs.get('filename') or kwargs.get('file')
            if not target: return "Error: No file name provided."
            return search_file(target)

        def format_read_file(file_path: str = None, path: str = None, file: str = None, **kwargs) -> str:
            target = file_path or path or file or kwargs.get('filename') or kwargs.get('filepath')
            if not target: return "Error: No file path provided."
            return read_file(target)
            
        def format_create_folder(folder_name: str = None, name: str = None, directory: str = None, **kwargs) -> str:
            target = folder_name or name or directory or kwargs.get('path') or kwargs.get('dir')
            if not target: return "Error: No folder name provided."
            return wrap_bool_result(create_folder, "Folder created.")(target)
            
        def format_list_directory(directory_path: str = None, path: str = None, directory: str = None, **kwargs) -> str:
            target = directory_path or path or directory or kwargs.get('dir') or kwargs.get('folder')
            if not target: return "Error: No directory path provided."
            return wrap_bool_result(list_directory, "Directory listed.")(target)
        
        def format_copy_file(source_path: str = None, destination_path: str = None, **kwargs) -> str:
            src = source_path or kwargs.get('source') or kwargs.get('src') or kwargs.get('from_path')
            dst = destination_path or kwargs.get('destination') or kwargs.get('dest') or kwargs.get('to_path')
            if not src or not dst: return "Error: Source and destination paths required."
            return wrap_bool_result(copy_file, "File copied.")(src, dst)

        def format_move_file(source_path: str = None, destination_path: str = None, **kwargs) -> str:
            src = source_path or kwargs.get('source') or kwargs.get('src') or kwargs.get('from_path')
            dst = destination_path or kwargs.get('destination') or kwargs.get('dest') or kwargs.get('to_path')
            if not src or not dst: return "Error: Source and destination paths required."
            return wrap_bool_result(move_file, "File moved.")(src, dst)
            
        def format_delete_file(file_path: str = None, path: str = None, **kwargs) -> str:
            target = file_path or path or kwargs.get('file') or kwargs.get('filename')
            if not target: return "Error: No file path provided."
            return wrap_bool_result(delete_file, "File deleted.")(target)

        # --- 1. SYSTEM TOOLS (Hardware, OS, Files) ---
        system_tools = [
            Tool("get_datetime_info", get_datetime_info,
     "Return ONLY current time/date/day. Trigger: 'what time', 'current date', 'what day is it'. EXCLUDE: 'agenda', 'schedule' → use calendar.",
     ToolCategory.SYSTEM, {'query': 'str'}),

Tool("system_status", generate_system_summary,
     "General system summary: CPU+RAM+Disk+Network. Trigger: 'system status', 'performance report'.",
     ToolCategory.SYSTEM),

Tool("open_program", format_open_program,
     "Launch DESKTOP APPS (Chrome/VSCode/Word). Trigger: 'open app', 'start ___'. EXCLUDE: 'open file' → read_file.",
     ToolCategory.SYSTEM, {'app_name': 'str'}),

Tool("search_file", format_search_file,
     "FIND files by name (returns PATH only). Trigger: 'find file', 'where is file', 'locate ___'.",
     ToolCategory.SYSTEM, {'file_name': 'str'}),

Tool("read_file", format_read_file,
     "Open and DISPLAY file contents (.txt/.pdf/.json). Trigger: 'read file', 'show content'.",
     ToolCategory.SYSTEM, {'file_path': 'str'}),

Tool("open_website", open_website,
     "Open URL/Search Google. Trigger: 'open website', 'google ___', 'search for ___'.",
     ToolCategory.SYSTEM, {'query': 'str'}),

Tool("copy_file", format_copy_file,
     "Duplicate file. Trigger: 'copy file'.",
     ToolCategory.SYSTEM, {'source_path': 'str','destination_path':'str'}),

Tool("move_file", format_move_file,
     "Move file. Trigger: 'move file'.",
     ToolCategory.SYSTEM, {'source_path':'str','destination_path':'str'}),

Tool("delete_file", format_delete_file,
     "Delete FILE permanently. Trigger: 'delete file'.",
     ToolCategory.SYSTEM, {'file_path':'str'}, requires_confirmation=True),

Tool("create_folder", format_create_folder,
     "Create folder. Trigger: 'make folder'.",
     ToolCategory.SYSTEM, {'folder_name':'str'}),

Tool("list_directory", format_list_directory,
     "List files in folder. Trigger: 'ls', 'dir', 'what's in folder'.",
     ToolCategory.SYSTEM, {'directory_path':'str'}),

Tool("terminate_program", format_terminate_program,
     "Kill/stop app. Trigger: 'close app', 'kill process'.",
     ToolCategory.SYSTEM, {'process_name':'str'}, requires_confirmation=True),

Tool("get_cpu_usage", format_cpu_usage, "CPU usage.", ToolCategory.SYSTEM),
Tool("get_memory_usage", format_memory_usage, "RAM usage.", ToolCategory.SYSTEM),
Tool("get_disk_usage", format_disk_usage, "Disk usage.", ToolCategory.SYSTEM, {'path':'str'}),
Tool("get_battery_info", format_battery_info, "Battery status.", ToolCategory.SYSTEM),
Tool("get_network_info", format_network_info, "Network stats.", ToolCategory.SYSTEM),
Tool("get_system_uptime", format_system_uptime, "System uptime.", ToolCategory.SYSTEM),
Tool("get_running_processes", format_running_processes, "List processes.", ToolCategory.SYSTEM, {'count':'int'}),
Tool("get_gpu_stats", format_gpu_stats, "GPU stats.", ToolCategory.SYSTEM),

Tool("get_temperature_sensors", format_temperature_sensors,
     "Hardware temperature sensors: CPU/GPU only. Trigger: 'device temperature', 'heat levels'.",
     ToolCategory.SYSTEM),

Tool("check_system_alerts", format_system_alerts,
     "Reports performance alerts: overheating, high CPU/RAM/disk. Trigger: 'issues', 'alerts', 'is system healthy?'.",
     ToolCategory.SYSTEM),

Tool("get_full_system_report", get_full_system_report,
     "Comprehensive detailed system report (all metrics). Trigger: 'full system report', 'detailed diagnostics', 'complete status'.",
     ToolCategory.SYSTEM),
        ]

        # --- 2. INFORMATION TOOLS (Web, Math, News) ---
        info_tools = [
          Tool("get_news", get_news_async,
     "Fetch CURRENT news headlines. Trigger: 'news today', 'latest headlines', 'tech news', 'sports news'. Categories: general, business, technology, sports, health, science, entertainment.",
     ToolCategory.INFORMATION),

Tool("get_weather", get_weather_async,
     "Get CURRENT weather + forecast. Trigger: 'weather in ___', 'is it raining', 'temperature in ___', 'will it rain'. Default: India if no location.",
     ToolCategory.INFORMATION, {'location':'str'}),

Tool("wikipedia_search", wikipedia_search_async,
     "Get Wikipedia summary for CONCEPTS/PEOPLE/HISTORY. Trigger: 'who is ___', 'what is ___', 'explain ___', 'history of ___'. EXCLUDE: 'latest news', 'current events' → use get_news.",
     ToolCategory.INFORMATION, {'query':'str'}),

Tool("calculate", calculate,
     "Evaluate math expressions. Supports: +, -, *, /, **, %, sqrt, sin, cos, log. Trigger: '5+5', 'square root of 16', 'percentage of ___', 'solve ___'.",
     ToolCategory.INFORMATION, {'expression':'str'}),

Tool("convert_temperature", convert_temperature,
     "Convert temperature units. Trigger: 'convert C to F'.",
     ToolCategory.INFORMATION, {'value':'float','from_unit':'str','to_unit':'str'}),

Tool("convert_length", convert_length,
     "Convert length units. Trigger: 'mm to cm', 'm to ft', 'km to miles'.",
     ToolCategory.INFORMATION, {'value':'float','from_unit':'str','to_unit':'str'}),

        ]

        note_tools = [
            Tool("create_note", create_note,
     "Create a QUICK NOTE (stored in database, not file). Trigger: 'take note', 'save note about'. EXCLUDE: 'create file', 'write file' → use file operations.",
     ToolCategory.PRODUCTIVITY, {'title':'str','content':'str'}),

Tool("list_notes", list_notes,
     "Show all saved NOTES. Trigger: 'show notes', 'list notes'.",
     ToolCategory.PRODUCTIVITY),

Tool("get_note", get_note,
     "Read a note by ID. Trigger: 'open note', 'read note 1'. Not files.",
     ToolCategory.PRODUCTIVITY, {'note_id':'int'}),

Tool("update_note", update_note,
     "Edit note title/content. Trigger: 'edit note', 'update note'.",
     ToolCategory.PRODUCTIVITY, {'note_id':'int'}),

Tool("delete_note", delete_note,
     "Delete a NOTE permanently. Trigger: 'delete note', 'remove note'.",
     ToolCategory.PRODUCTIVITY, {'note_id':'int'}, requires_confirmation=True),

Tool("get_notes_summary", get_notes_summary,
     "Count and summary of notes. Trigger: 'notes summary', 'notes overview'.",
     ToolCategory.PRODUCTIVITY),

Tool("search_notes", list_notes,
     "Search/filter notes by tag. Trigger: 'find notes tagged ___', 'notes about ___', 'search notes for'.",
     ToolCategory.PRODUCTIVITY, {'tag':'str'}),

        ]

        communication_tools = [
            Tool("tell_joke", tell_joke,
     "Return a joke. Trigger: 'tell joke', 'make me laugh'.",
     ToolCategory.COMMUNICATION),
     

        ]

        task_tools = [
            Tool("add_task", add_task,
     "Create a TODO in task list (NO TIME attached). Trigger: 'add task', 'todo: ___', 'I need to ___'. EXCLUDE: 'remind me at/in/tomorrow' → use add_reminder.",
     ToolCategory.PRODUCTIVITY, {'task_content':'str'}),

Tool("list_tasks", list_tasks,
     "Show all tasks (pending/completed). Trigger: 'show todos', 'list tasks', 'tasks left'.",
     ToolCategory.PRODUCTIVITY),

Tool("complete_task", complete_task,
     "Mark task completed. Trigger: 'mark done', 'task finished', 'complete task X'.",
     ToolCategory.PRODUCTIVITY, {'identifier':'str'}),

Tool("delete_task", delete_task,
     "Delete a task permanently. Trigger: 'remove task', 'delete todo X'.",
     ToolCategory.PRODUCTIVITY, {'identifier':'str'}, requires_confirmation=True),

Tool("get_task_summary", get_task_summary,
     "Task summary counts (pending vs completed). Trigger: 'task summary', 'todo overview'.",
     ToolCategory.PRODUCTIVITY),

        ]
        reminder_tools = [
           Tool("add_reminder", add_reminder,
     "Set time-based ALERT (will notify you). Trigger: 'remind me at 5pm', 'remind me in 10 mins', 'alert me when'. EXCLUDE: 'schedule meeting' → use add_event.",
     ToolCategory.PRODUCTIVITY, {'title':'str','time_str':'str'}),

Tool("list_reminders", list_reminders,
     "Show active reminders. Trigger: 'show reminders', 'what should I remember'.",
     ToolCategory.PRODUCTIVITY),

Tool("delete_reminder", delete_reminder,
     "Delete reminder by ID. Trigger: 'remove reminder'.",
     ToolCategory.PRODUCTIVITY, {'reminder_id':'int'}),

Tool("set_timer", set_timer_async,
     "Countdown timer (immediate start). Trigger: 'set timer for 5 mins', 'countdown ___'. EXCLUDE: 'remind me later' → use add_reminder.",
     ToolCategory.PRODUCTIVITY, {'duration_seconds':'int'}),

        ]
        
        calendar_tools = [
            Tool("add_event", add_event,
     "Add CALENDAR event with start/end time. Trigger: 'schedule ___', 'book meeting', 'add appointment'. EXCLUDE: 'remind me' → use add_reminder.",
     ToolCategory.PRODUCTIVITY, {'title':'str','start_time':'str'}),

Tool("list_events", list_events,
     "List calendar events. Trigger: 'show calendar events', 'events this week'.",
     ToolCategory.PRODUCTIVITY),

Tool("get_today_agenda", get_today_agenda,
     "TODAY'S calendar events ONLY. Trigger: 'what's on today', 'today's schedule', 'my agenda'. EXCLUDE: 'current time' → use get_datetime_info.",
     ToolCategory.PRODUCTIVITY),

Tool("get_upcoming_events", get_upcoming_events,
     "Show NEXT upcoming events. Trigger: 'what's coming up', 'upcoming meetings'.",
     ToolCategory.PRODUCTIVITY, {'hours':'int'}),

Tool("delete_event", delete_event,
     "Delete calendar event. Trigger: 'cancel event', 'remove event'.",
     ToolCategory.PRODUCTIVITY, {'identifier':'str'}, requires_confirmation=True),

Tool("update_event", update_event,
     "Modify calendar event details (title/time/location). Trigger: 'reschedule meeting', 'change event time', 'update appointment'.",
     ToolCategory.PRODUCTIVITY, {'event_id':'int','title':'str','start_time':'str','end_time':'str','location':'str'}),

Tool("get_event", get_event,
     "Get specific calendar event details by ID. Trigger: 'event details', 'info about event #X'.",
     ToolCategory.PRODUCTIVITY, {'event_id':'int'}),

        ]
        
        pomodoro_tools = [
           Tool("start_pomodoro", start_pomodoro,
     "Start work session timer. Trigger: 'start focus', 'begin pomodoro', '25 min work'.",
     ToolCategory.PRODUCTIVITY, {'task_name':'str'}),

Tool("stop_pomodoro", stop_pomodoro,
     "Stop current pomodoro session. Trigger: 'stop pomodoro', 'cancel focus'.",
     ToolCategory.PRODUCTIVITY),

Tool("get_pomodoro_status", get_pomodoro_status,
     "Current session remaining time. Trigger: 'pomodoro progress', 'time left in session'.",
     ToolCategory.PRODUCTIVITY),

Tool("get_pomodoro_stats", get_pomodoro_stats,
     "Completed pomodoros history summary. Trigger: 'focus stats', 'how many sessions done'.",
     ToolCategory.PRODUCTIVITY),

Tool("start_break", start_break,
     "Start break timer. Trigger: 'take a break', 'start rest', 'begin short/long break'.",
     ToolCategory.PRODUCTIVITY, {'break_type':'str'}),

        ]
        
        # Register all tools
        for tool_list in [system_tools, info_tools, communication_tools, task_tools, note_tools, reminder_tools, calendar_tools, pomodoro_tools]:
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
    
    async def _select_tool(self, command: str) -> Tuple[Optional[str], Dict[str, Any]]:
        """DEPRECATED: Replaced by native function calling."""
        return None, {}

    def _get_gemini_tools_schema(self, allowed_tools: Optional[List[str]] = None):
        """
        Convert registered tools to Gemini Function Declarations.
        Args:
            allowed_tools: If provided, only include these tools in the schema.
        """
        fds = []
        target_tools = self.tools
        
        if allowed_tools is not None:
            target_tools = {k: v for k, v in self.tools.items() if k in allowed_tools}
            
        for name, tool in target_tools.items():
            parameters = {
                "type": "OBJECT",
                "properties": {},
                "required": []
            }
            
            for param_name, param_type in tool.parameters.items():
                ptype = "STRING"
                if param_type == 'int': ptype = "INTEGER"
                elif param_type == 'float': ptype = "NUMBER"
                elif param_type == 'bool': ptype = "BOOLEAN"
                
                parameters["properties"][param_name] = {"type": ptype}
                parameters["required"].append(param_name)
            
            fds.append(genai.protos.FunctionDeclaration(
                name=name,
                description=tool.description,
                parameters=parameters
            ))
            
        return genai.protos.Tool(function_declarations=fds)
    
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
            context_summary=self.conversation_manager.get_context_summary()
        )
        
        history = self.conversation_manager.get_formatted_history(last_n=8)
        
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
            self.conversation_manager.add('user', prompt)
            self.conversation_manager.add('assistant', reply)
            update_memory(prompt, reply)
            
            return reply.strip()
            
        except Exception as e:
            logger.error(f"Conversational reply error: {e}", exc_info=True)
            return "I'm having trouble processing that right now."
    
    async def process_command(self, command: str, source: str = "text") -> str:
        """
        [Public Service API] Process a user command and return the response.
        Generates a unique Request ID for the duration of this command.
        """
        import uuid
        req_id = str(uuid.uuid4())[:8]
        token = request_id_ctx.set(req_id)
        
        logger.info(f"Processing command from {source}: '{command}'")
        
        try:
            return await self._process_command_internal(command)
        except Exception as e:
            logger.error(f"Error command processing: {e}", exc_info=True)
            return f"I encountered an error: {str(e)}"
        finally:
            request_id_ctx.reset(token)

    async def _process_command_internal(self, command: str) -> str:
        """Process a user command using Gemini Native Function Calling and Smart Selection."""
        if not command or not command.strip():
            return "I didn't catch that. Could you repeat?"
        
        command = command.strip()
        logger.info(f"Processing command: {command[:50]}...")
        
        context = self.identity_prompt.format(
            current_time=datetime.now().strftime('%I:%M %p on %A, %B %d'),
            context_summary=self.conversation_manager.get_context_summary()
        )
        history = self.conversation_manager.get_formatted_history(last_n=5)
        
        full_prompt = f"""{context}\n\nRecent history:\n{history}\n\nUser: {command}\n(Use a tool if appropriate, otherwise respond conversationally.)"""

        try:
            # --- 1. PREDICT RELEVANT TOOLS ---
            # This is the key optimization: Filter tools before calling API
            relevant_tools = self._predict_relevant_tools(command)
            
            # If the classifier strongly believes this is just conversation, 
            # skip tool schema generation entirely (saves tokens + latency)
            if relevant_tools == ["conversational"]:
                logger.info("Skipping tool schema generation based on classifier.")
                return await self._conversational_reply(command)

            # --- 2. GENERATE TOOLS SCHEMA (FILTERED) ---
            # Only send definitions for tools deemed relevant
            tools_obj = self._get_gemini_tools_schema(allowed_tools=relevant_tools)
            
            # --- 3. CALL GEMINI ---
            response = await asyncio.to_thread(
                self.model.generate_content,
                full_prompt,
                tools=[tools_obj]
            )
            
            # --- 4. HANDLE RESPONSE ---
            function_call = None
            if hasattr(response, 'candidates') and response.candidates:
                part = response.candidates[0].content.parts[0]
                if hasattr(part, 'function_call') and part.function_call:
                    function_call = part.function_call
            
            if function_call:
                tool_name = function_call.name
                args = dict(function_call.args)
                
                if tool_name not in self.tools:
                    return await self._conversational_reply(command)
                
                tool = self.tools[tool_name]
                
                if tool.requires_confirmation and not self.debug_mode:
                    if self.voice_enabled:
                         self.voice_service.speak(f"Are you sure you want to {tool_name.replace('_', ' ')}? Say yes to confirm.")
                    # Confirmation logic skipped for automation as per instructions
                    pass 

                success, result = await self.tool_executor.execute(tool, args)
                
                if success:
                    formatted = self._format_tool_result(result)
                    self.conversation_manager.add('user', command, tool_used=tool_name)
                    self.conversation_manager.add('assistant', formatted, tool_used=tool_name)
                    if self.voice_enabled:
                        self.voice_service.speak(formatted)
                    return formatted
                else:
                    error_msg = f"I couldn't complete that action. {result}"
                    if self.voice_enabled:
                        self.voice_service.speak(error_msg)
                    return error_msg
            
            else:
                reply = self._extract_response_text(response)
                if not reply: reply = "I'm not sure how to respond."
                if self.voice_enabled: self.voice_service.speak(reply)
                self.conversation_manager.add('user', command)
                self.conversation_manager.add('assistant', reply)
                return reply
                
        except Exception as e:
            logger.error(f"Error in native tool execution: {e}", exc_info=True)
            return "I encountered an error processing your request."
    
    async def generate_daily_brief(self) -> str:
        """Generate a comprehensive daily briefing with improved error handling."""
        now = datetime.now()
        parts = [f"{get_greeting()}!"]
        parts.append(f"It's {now.strftime('%I:%M %p')} on {now.strftime('%A, %B %d')}.")
        
        # Tasks - with better error handling and formatting
        try:
            task_summary = await get_task_summary()
            if task_summary and isinstance(task_summary, str) and task_summary.strip():
                parts.append(task_summary)
            else:
                logger.debug("No task summary available")
        except Exception as e:
            logger.warning(f"Could not get task summary: {e}", exc_info=False)
            parts.append("Tasks: Unable to retrieve summary.")
        
        # Reminders - with validation
        try:
            reminders = await list_reminders()
            if reminders:
                reminder_count = len(reminders)
                reminder_text = f"You have {reminder_count} active reminder{'s' if reminder_count != 1 else ''}."
                parts.append(reminder_text)
            else:
                parts.append("No active reminders.")
        except Exception as e:
            logger.warning(f"Could not get reminders: {e}", exc_info=False)
            parts.append("Reminders: Unable to retrieve.")
        
        # Calendar - show today's events
        try:
            calendar_summary = await get_calendar_summary()
            if calendar_summary and isinstance(calendar_summary, str):
                parts.append(calendar_summary)
        except Exception as e:
            logger.warning(f"Could not get calendar summary: {e}", exc_info=False)
        
        # Weather - with validation and error recovery
        try:
           
            weather = await get_weather_async(self.config.get('default_location', config.DEFAULT_LOCATION))
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
                logger.debug("Listening for speech input...")
                # DIRECT AWAIT - No asyncio.run()
                result = await asyncio.wait_for(
                    asyncio.to_thread(recognize_speech), 
                    timeout=config.SPEECH_LISTEN_TIMEOUT
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
        # Show daily brief on startup
        try:
            brief = await self.generate_daily_brief()
            self._speak(brief)  # Sync call
        except Exception as e:
            logger.warning(f"Could not generate daily brief: {e}")
        
        exit_commands = {'exit', 'goodbye', 'quit', 'bye', 'stop', 'sleep'}
        consecutive_failures = 0
        max_failures = config.MAX_CONSECUTIVE_FAILURES
        
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
                        timeout=config.COMMAND_PROCESSING_TIMEOUT
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
        
        # CRITICAL: Initialize database BEFORE starting any background services
        # This prevents race conditions where reminder monitoring tries to query tables that don't exist yet
        logger.info("Initializing database...")
        asyncio.run(init_db_async())
        
        # NOW it's safe to start reminder monitoring (database tables exist)
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
        finally:
            self.shutdown()

    def shutdown(self):
        """Enhanced shutdown with resource cleanup."""
        self.running = False
        
        try:
            self.reminder_manager.stop_monitoring()
            save_memory()
            logger.info("Amadeus shutdown complete")
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