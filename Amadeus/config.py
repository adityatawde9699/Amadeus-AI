"""
Centralized configuration management for Amadeus AI Assistant.
All configuration values are loaded from environment variables with sensible defaults.
"""

import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from dotenv import load_dotenv

# Load .env at import time so other modules can rely on environment vars
load_dotenv()

logger = logging.getLogger(__name__)

# ============================================================================
# BASE CONFIGURATION
# ============================================================================

BASE_DIR = Path(__file__).resolve().parent

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================

DB_FILE = os.getenv('AMADEUS_DB_FILE', str(BASE_DIR / 'amadeus.db'))
DB_URL = f"sqlite:///{DB_FILE}"

# Connection Pool Settings
DB_POOL_SIZE = int(os.getenv('DB_POOL_SIZE', '5'))  # Number of connections to maintain
DB_MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', '10'))  # Max connections beyond pool_size
DB_POOL_TIMEOUT = int(os.getenv('DB_POOL_TIMEOUT', '30'))  # Seconds to wait for connection
DB_POOL_RECYCLE = int(os.getenv('DB_POOL_RECYCLE', '3600'))  # Seconds before recycling connection
DB_ECHO = os.getenv('DB_ECHO', 'false').lower() in ('1', 'true', 'yes')  # SQL logging

# ============================================================================
# APPLICATION SETTINGS
# ============================================================================

# Voice and Speech Settings
VOICE_ENABLED = os.getenv('VOICE_ENABLED', 'true').lower() in ('1', 'true', 'yes')
TTS_RATE = int(os.getenv('TTS_RATE', '150'))  # Speech rate (words per minute)
TTS_VOICE_INDEX = int(os.getenv('TTS_VOICE_INDEX', '1'))  # Voice index (0 or 1)

# Whisper Speech Recognition Settings
WHISPER_MODEL = os.getenv('WHISPER_MODEL', 'tiny')  # tiny, base, small, medium, large
WHISPER_DEVICE = os.getenv('WHISPER_DEVICE', 'cpu')  # cpu, cuda
WHISPER_COMPUTE_TYPE = os.getenv('WHISPER_COMPUTE_TYPE', 'int8')  # int8, float16, float32
WHISPER_BEAM_SIZE = int(os.getenv('WHISPER_BEAM_SIZE', '1'))

# Speech Recognition Settings
SPEECH_RECOGNITION_TIMEOUT = int(os.getenv('SPEECH_RECOGNITION_TIMEOUT', '10'))  # seconds
SPEECH_PHRASE_TIME_LIMIT = int(os.getenv('SPEECH_PHRASE_TIME_LIMIT', '10'))  # seconds
SPEECH_ENERGY_THRESHOLD = int(os.getenv('SPEECH_ENERGY_THRESHOLD', '300'))
SPEECH_MIN_AUDIO_LENGTH = int(os.getenv('SPEECH_MIN_AUDIO_LENGTH', '32000'))  # bytes (~1 second)

# ============================================================================
# AI MODEL CONFIGURATION
# ============================================================================

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')

# ============================================================================
# ASSISTANT IDENTITY CONFIGURATION
# ============================================================================

ASSISTANT_NAME = os.getenv('ASSISTANT_NAME', 'Amadeus')
ASSISTANT_PERSONALITY = os.getenv('ASSISTANT_PERSONALITY', 'helpful, concise, and friendly')
DEFAULT_LOCATION = os.getenv('DEFAULT_LOCATION', 'India')
TIMEZONE = os.getenv('TIMEZONE', 'Asia/Kolkata')

# ============================================================================
# CONVERSATION SETTINGS
# ============================================================================

CONVERSATION_MAX_MESSAGES = int(os.getenv('CONVERSATION_MAX_MESSAGES', '20'))
CONVERSATION_MAX_TOKENS_ESTIMATE = int(os.getenv('CONVERSATION_MAX_TOKENS_ESTIMATE', '4000'))
CONVERSATION_HISTORY_LAST_N = int(os.getenv('CONVERSATION_HISTORY_LAST_N', '10'))

# ============================================================================
# TOOL EXECUTION SETTINGS
# ============================================================================

TOOL_MAX_RETRIES = int(os.getenv('TOOL_MAX_RETRIES', '2'))
TOOL_RETRY_DELAY = float(os.getenv('TOOL_RETRY_DELAY', '0.5'))  # seconds

# ============================================================================
# TIMEOUT SETTINGS
# ============================================================================

COMMAND_PROCESSING_TIMEOUT = float(os.getenv('COMMAND_PROCESSING_TIMEOUT', '30.0'))  # seconds
SPEECH_LISTEN_TIMEOUT = float(os.getenv('SPEECH_LISTEN_TIMEOUT', '10.0'))  # seconds
MAX_CONSECUTIVE_FAILURES = int(os.getenv('MAX_CONSECUTIVE_FAILURES', '3'))

# ============================================================================
# REMINDER SETTINGS
# ============================================================================

REMINDER_CHECK_INTERVAL = int(os.getenv('REMINDER_CHECK_INTERVAL', '30'))  # seconds
REMINDER_LOOP_STARTUP_TIMEOUT = float(os.getenv('REMINDER_LOOP_STARTUP_TIMEOUT', '5.0'))  # seconds
REMINDER_LOOP_STOP_TIMEOUT = float(os.getenv('REMINDER_LOOP_STOP_TIMEOUT', '5.0'))  # seconds

# ============================================================================
# SYSTEM MONITORING SETTINGS
# ============================================================================

SYSTEM_MONITOR_CPU_THRESHOLD = int(os.getenv('SYSTEM_MONITOR_CPU_THRESHOLD', '85'))  # percentage
SYSTEM_MONITOR_MEMORY_THRESHOLD = int(os.getenv('SYSTEM_MONITOR_MEMORY_THRESHOLD', '80'))  # percentage
SYSTEM_MONITOR_DISK_THRESHOLD = int(os.getenv('SYSTEM_MONITOR_DISK_THRESHOLD', '90'))  # percentage
SYSTEM_MONITOR_TEMPERATURE_THRESHOLD = int(os.getenv('SYSTEM_MONITOR_TEMPERATURE_THRESHOLD', '80'))  # Celsius
SYSTEM_MONITOR_GPU_LOAD_THRESHOLD = int(os.getenv('SYSTEM_MONITOR_GPU_LOAD_THRESHOLD', '85'))  # percentage
SYSTEM_MONITOR_CHECK_INTERVAL = int(os.getenv('SYSTEM_MONITOR_CHECK_INTERVAL', '60'))  # seconds
SYSTEM_MONITOR_CPU_CHECK_INTERVAL = float(os.getenv('SYSTEM_MONITOR_CPU_CHECK_INTERVAL', '0.1'))  # seconds

# ============================================================================
# FILE OPERATION SETTINGS
# ============================================================================

FILE_SEARCH_MAX_RESULTS = int(os.getenv('FILE_SEARCH_MAX_RESULTS', '10'))
FILE_READ_MAX_CHARS = int(os.getenv('FILE_READ_MAX_CHARS', '5000'))
APP_LAUNCH_TIMEOUT = int(os.getenv('APP_LAUNCH_TIMEOUT', '15'))  # seconds

# ============================================================================
# API SETTINGS
# ============================================================================

NEWS_API_KEY = os.getenv('NEWS_API_KEY', '')
WEATHER_API_KEY = os.getenv('WEATHER_API_KEY', '')

# News API Settings
NEWS_DEFAULT_CATEGORY = os.getenv('NEWS_DEFAULT_CATEGORY', 'general')
NEWS_DEFAULT_COUNTRY = os.getenv('NEWS_DEFAULT_COUNTRY', 'in')
NEWS_DEFAULT_COUNT = int(os.getenv('NEWS_DEFAULT_COUNT', '5'))

# Weather API Settings
WEATHER_API_BASE_URL = os.getenv('WEATHER_API_BASE_URL', 'http://api.openweathermap.org/data/2.5/weather')
WEATHER_API_TIMEOUT = int(os.getenv('WEATHER_API_TIMEOUT', '10'))  # seconds

# Wikipedia API Settings
WIKIPEDIA_API_BASE_URL = os.getenv('WIKIPEDIA_API_BASE_URL', 'https://en.wikipedia.org/api/rest_v1/page/summary')
WIKIPEDIA_DEFAULT_SENTENCES = int(os.getenv('WIKIPEDIA_DEFAULT_SENTENCES', '3'))
WIKIPEDIA_API_TIMEOUT = int(os.getenv('WIKIPEDIA_API_TIMEOUT', '10'))  # seconds

# ============================================================================
# CALENDAR SETTINGS
# ============================================================================

CALENDAR_DEFAULT_EVENT_DURATION = int(os.getenv('CALENDAR_DEFAULT_EVENT_DURATION', '60'))  # minutes
CALENDAR_REMINDER_BEFORE_MINUTES = int(os.getenv('CALENDAR_REMINDER_BEFORE_MINUTES', '15'))
CALENDAR_MAX_EVENTS_DISPLAY = int(os.getenv('CALENDAR_MAX_EVENTS_DISPLAY', '10'))
CALENDAR_DAYS_AHEAD_DEFAULT = int(os.getenv('CALENDAR_DAYS_AHEAD_DEFAULT', '7'))

# ============================================================================
# POMODORO SETTINGS
# ============================================================================

POMODORO_DEFAULT_DURATION = int(os.getenv('POMODORO_DEFAULT_DURATION', '25'))  # minutes
POMODORO_SHORT_BREAK = int(os.getenv('POMODORO_SHORT_BREAK', '5'))  # minutes
POMODORO_LONG_BREAK = int(os.getenv('POMODORO_LONG_BREAK', '15'))  # minutes
POMODORO_SESSIONS_BEFORE_LONG_BREAK = int(os.getenv('POMODORO_SESSIONS_BEFORE_LONG_BREAK', '4'))

# ============================================================================
# STABILITY SETTINGS  
# ============================================================================

DB_MAX_RETRIES = int(os.getenv('DB_MAX_RETRIES', '3'))
DB_RETRY_DELAY = float(os.getenv('DB_RETRY_DELAY', '0.5'))  # seconds
API_GRACEFUL_DEGRADATION = os.getenv('API_GRACEFUL_DEGRADATION', 'true').lower() in ('1', 'true', 'yes')

# ============================================================================
# DISPLAY SETTINGS
# ============================================================================

DISPLAY_PROCESSES_COUNT = int(os.getenv('DISPLAY_PROCESSES_COUNT', '10'))
DISPLAY_PROCESSES_VOICE_COUNT = int(os.getenv('DISPLAY_PROCESSES_VOICE_COUNT', '5'))
DISPLAY_TEMPERATURE_SENSORS_LIMIT = int(os.getenv('DISPLAY_TEMPERATURE_SENSORS_LIMIT', '3'))
DISPLAY_ALERTS_LIMIT = int(os.getenv('DISPLAY_ALERTS_LIMIT', '5'))

# ============================================================================
# CONFIGURATION VALIDATION
# ============================================================================

def validate_config() -> Dict[str, Any]:
    """
    Validate configuration values and return a report.
    
    Returns:
        Dict with validation results including errors and warnings
    """
    errors = []
    warnings = []
    
    # Required API keys
    if not GEMINI_API_KEY:
        errors.append("GEMINI_API_KEY is required but not set")
    
    # Validate numeric ranges
    if TTS_RATE < 50 or TTS_RATE > 300:
        warnings.append(f"TTS_RATE ({TTS_RATE}) is outside recommended range (50-300)")
    
    if CONVERSATION_MAX_MESSAGES < 5 or CONVERSATION_MAX_MESSAGES > 100:
        warnings.append(f"CONVERSATION_MAX_MESSAGES ({CONVERSATION_MAX_MESSAGES}) is outside recommended range (5-100)")
    
    if TOOL_MAX_RETRIES < 0 or TOOL_MAX_RETRIES > 10:
        warnings.append(f"TOOL_MAX_RETRIES ({TOOL_MAX_RETRIES}) is outside recommended range (0-10)")
    
    if COMMAND_PROCESSING_TIMEOUT < 5 or COMMAND_PROCESSING_TIMEOUT > 300:
        warnings.append(f"COMMAND_PROCESSING_TIMEOUT ({COMMAND_PROCESSING_TIMEOUT}) is outside recommended range (5-300)")
    
    # Validate timezone
    try:
        # Try to use zoneinfo (Python 3.9+)
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(TIMEZONE)
        except ImportError:
            # Fallback to pytz
            try:
                import pytz
                pytz.timezone(TIMEZONE)
            except ImportError:
                warnings.append("No timezone library available. Install pytz for timezone support.")
            except pytz.exceptions.UnknownTimeZoneError:
                errors.append(f"Invalid TIMEZONE: {TIMEZONE}")
    except Exception as e:
        warnings.append(f"Could not validate timezone {TIMEZONE}: {e}")
    
    # Validate Whisper model
    valid_whisper_models = ['tiny', 'base', 'small', 'medium', 'large']
    if WHISPER_MODEL not in valid_whisper_models:
        warnings.append(f"WHISPER_MODEL ({WHISPER_MODEL}) should be one of {valid_whisper_models}")
    
    # Validate device
    if WHISPER_DEVICE not in ['cpu', 'cuda']:
        warnings.append(f"WHISPER_DEVICE ({WHISPER_DEVICE}) should be 'cpu' or 'cuda'")
    
    # Validate thresholds
    if not (0 <= SYSTEM_MONITOR_CPU_THRESHOLD <= 100):
        warnings.append(f"SYSTEM_MONITOR_CPU_THRESHOLD ({SYSTEM_MONITOR_CPU_THRESHOLD}) should be between 0 and 100")
    
    if not (0 <= SYSTEM_MONITOR_MEMORY_THRESHOLD <= 100):
        warnings.append(f"SYSTEM_MONITOR_MEMORY_THRESHOLD ({SYSTEM_MONITOR_MEMORY_THRESHOLD}) should be between 0 and 100")
    
    # Optional API keys
    if not NEWS_API_KEY:
        warnings.append("NEWS_API_KEY not set - news features will be unavailable")
    
    if not WEATHER_API_KEY:
        warnings.append("WEATHER_API_KEY not set - weather features will be unavailable")
    
    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings
    }


def get_system_thresholds() -> Dict[str, int]:
    """Get system monitoring thresholds as a dictionary."""
    return {
        'cpu': SYSTEM_MONITOR_CPU_THRESHOLD,
        'memory': SYSTEM_MONITOR_MEMORY_THRESHOLD,
        'disk': SYSTEM_MONITOR_DISK_THRESHOLD,
        'temperature': SYSTEM_MONITOR_TEMPERATURE_THRESHOLD,
        'gpu_load': SYSTEM_MONITOR_GPU_LOAD_THRESHOLD
    }


def get_assistant_config() -> Dict[str, Any]:
    """Get assistant identity configuration as a dictionary."""
    return {
        'name': ASSISTANT_NAME,
        'personality': ASSISTANT_PERSONALITY,
        'default_location': DEFAULT_LOCATION,
        'timezone': TIMEZONE
    }


def log_config_summary():
    """Log a summary of current configuration (excluding sensitive data)."""
    logger.info("=== Amadeus Configuration Summary ===")
    logger.info(f"Assistant: {ASSISTANT_NAME}")
    logger.info(f"Location: {DEFAULT_LOCATION}, Timezone: {TIMEZONE}")
    logger.info(f"Voice Enabled: {VOICE_ENABLED}")
    logger.info(f"Gemini Model: {GEMINI_MODEL}")
    logger.info(f"Conversation: max_messages={CONVERSATION_MAX_MESSAGES}, max_tokens={CONVERSATION_MAX_TOKENS_ESTIMATE}")
    logger.info(f"Tool Execution: max_retries={TOOL_MAX_RETRIES}, retry_delay={TOOL_RETRY_DELAY}s")
    logger.info(f"Timeouts: command={COMMAND_PROCESSING_TIMEOUT}s, speech={SPEECH_LISTEN_TIMEOUT}s")
    logger.info(f"Reminder Check Interval: {REMINDER_CHECK_INTERVAL}s")
    logger.info(f"System Thresholds: CPU={SYSTEM_MONITOR_CPU_THRESHOLD}%, Memory={SYSTEM_MONITOR_MEMORY_THRESHOLD}%")
    
    # Validate and log validation results
    validation = validate_config()
    if validation['errors']:
        logger.error("Configuration errors:")
        for error in validation['errors']:
            logger.error(f"  - {error}")
    
    if validation['warnings']:
        logger.warning("Configuration warnings:")
        for warning in validation['warnings']:
            logger.warning(f"  - {warning}")
    
    if validation['valid']:
        logger.info("Configuration is valid")


# Auto-validate on import (can be disabled if needed)
if os.getenv('SKIP_CONFIG_VALIDATION', 'false').lower() not in ('1', 'true', 'yes'):
    validation_result = validate_config()
    if not validation_result['valid']:
        logger.error("Configuration validation failed. Please fix the errors above.")
        # Don't raise exception, just log - allows for graceful degradation