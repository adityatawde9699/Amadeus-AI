"""
Centralized configuration management for Amadeus AI Assistant.

This module provides a type-safe, validated configuration system using
pydantic-settings. All configuration values are loaded from environment
variables with sensible defaults.

Usage:
    from src.core.config import get_settings
    
    settings = get_settings()
    print(settings.APP_NAME)
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    All settings have sensible defaults for development. Override them
    via environment variables or a .env file for production.
    """
    
    model_config = SettingsConfigDict(
        env_file=[".env", "Amadeus/.env"],
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # Ignore extra env vars
    )
    
    # =========================================================================
    # ENVIRONMENT
    # =========================================================================
    ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    
    # =========================================================================
    # PATHS
    # =========================================================================
    BASE_DIR: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent)
    DATA_DIR: Path = Field(default=None)  # Will be set in validator
    
    @field_validator("DATA_DIR", mode="before")
    @classmethod
    def set_data_dir(cls, v, info):
        """Set DATA_DIR relative to BASE_DIR if not provided."""
        if v is None:
            base = info.data.get("BASE_DIR", Path(__file__).parent.parent.parent)
            return base / "data"
        return Path(v)
    
    # =========================================================================
    # API KEYS
    # =========================================================================
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-2.5-flash"
    WEATHER_API_KEY: str | None = None
    NEWS_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None  # Reserved for future use
    
    # =========================================================================
    # DATABASE
    # =========================================================================
    DATABASE_URL: str = "sqlite:///./data/amadeus.db"
    
    # Connection Pool Settings
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=50)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0, le=100)
    DB_POOL_TIMEOUT: int = Field(default=30, ge=1, le=300)
    DB_POOL_RECYCLE: int = Field(default=3600, ge=60)
    DB_ECHO: bool = False
    
    # =========================================================================
    # SPEECH / VOICE
    # =========================================================================
    VOICE_ENABLED: bool = True
    WAKE_WORD: str = "amadeus"
    
    # TTS Settings
    TTS_RATE: int = Field(default=150, ge=50, le=300)
    TTS_VOICE_INDEX: int = Field(default=1, ge=0)
    
    # Whisper Settings
    WHISPER_MODEL: Literal["tiny", "base", "small", "medium", "large"] = "tiny"
    WHISPER_DEVICE: Literal["cpu", "cuda"] = "cpu"
    WHISPER_COMPUTE_TYPE: Literal["int8", "float16", "float32"] = "int8"
    WHISPER_BEAM_SIZE: int = Field(default=1, ge=1, le=10)
    
    # Speech Recognition Settings
    SPEECH_RECOGNITION_TIMEOUT: int = Field(default=5, ge=1, le=30)
    SPEECH_PHRASE_TIME_LIMIT: int = Field(default=10, ge=1, le=60)
    SPEECH_ENERGY_THRESHOLD: int = Field(default=4000, ge=100, le=10000)
    SPEECH_MIN_AUDIO_LENGTH: int = Field(default=3200, ge=100)
    
    # =========================================================================
    # ASSISTANT IDENTITY
    # =========================================================================
    ASSISTANT_NAME: str = "Amadeus"
    ASSISTANT_VERSION: str = "2.0.0"
    ASSISTANT_PERSONALITY: str = "helpful, concise, and friendly"
    DEFAULT_LOCATION: str = "India"
    TIMEZONE: str = "Asia/Kolkata"
    
    # =========================================================================
    # CONVERSATION
    # =========================================================================
    CONVERSATION_MAX_HISTORY: int = Field(default=20, ge=1, le=100)
    CONVERSATION_MAX_TOKENS_ESTIMATE: int = Field(default=4000, ge=100, le=32000)
    CONTEXT_SUMMARY_LENGTH: int = Field(default=500, ge=50, le=2000)
    
    # =========================================================================
    # TOOL EXECUTION
    # =========================================================================
    TOOL_MAX_RETRIES: int = Field(default=3, ge=1, le=10)
    TOOL_TIMEOUT: int = Field(default=60, ge=5, le=300)
    
    # =========================================================================
    # API SERVER
    # =========================================================================
    API_HOST: str = "0.0.0.0"
    API_PORT: int = Field(default=8000, ge=1, le=65535)
    API_WORKERS: int = Field(default=1, ge=1, le=32)
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:8501"
    
    # Rate Limiting
    RATE_LIMIT_REQUESTS: int = Field(default=100, ge=1)
    RATE_LIMIT_WINDOW_SECONDS: int = Field(default=60, ge=1)
    
    # =========================================================================
    # SYSTEM MONITORING THRESHOLDS
    # =========================================================================
    CPU_WARNING_THRESHOLD: int = Field(default=80, ge=1, le=100)
    CPU_CRITICAL_THRESHOLD: int = Field(default=95, ge=1, le=100)
    MEMORY_WARNING_THRESHOLD: int = Field(default=80, ge=1, le=100)
    MEMORY_CRITICAL_THRESHOLD: int = Field(default=95, ge=1, le=100)
    DISK_WARNING_THRESHOLD: int = Field(default=80, ge=1, le=100)
    DISK_CRITICAL_THRESHOLD: int = Field(default=95, ge=1, le=100)
    BATTERY_LOW_THRESHOLD: int = Field(default=20, ge=1, le=100)
    BATTERY_CRITICAL_THRESHOLD: int = Field(default=10, ge=1, le=100)
    
    # =========================================================================
    # FILE OPERATIONS
    # =========================================================================
    FILE_SEARCH_MAX_RESULTS: int = Field(default=10, ge=1, le=100)
    FILE_READ_MAX_CHARS: int = Field(default=5000, ge=100, le=100000)
    APP_LAUNCH_TIMEOUT: int = Field(default=15, ge=1, le=60)
    
    # =========================================================================
    # PRODUCTIVITY: REMINDERS
    # =========================================================================
    REMINDER_CHECK_INTERVAL: int = Field(default=30, ge=5, le=300)
    REMINDER_LOOP_STARTUP_TIMEOUT: float = Field(default=5.0, ge=1.0, le=30.0)
    REMINDER_LOOP_STOP_TIMEOUT: float = Field(default=5.0, ge=1.0, le=30.0)
    
    # =========================================================================
    # PRODUCTIVITY: POMODORO
    # =========================================================================
    POMODORO_WORK_DURATION: int = Field(default=25, ge=1, le=120)
    POMODORO_SHORT_BREAK: int = Field(default=5, ge=1, le=30)
    POMODORO_LONG_BREAK: int = Field(default=15, ge=1, le=60)
    POMODORO_CYCLES_BEFORE_LONG_BREAK: int = Field(default=4, ge=1, le=10)
    
    # =========================================================================
    # PRODUCTIVITY: CALENDAR
    # =========================================================================
    CALENDAR_DEFAULT_EVENT_DURATION: int = Field(default=60, ge=5, le=480)
    CALENDAR_REMINDER_BEFORE_MINUTES: int = Field(default=15, ge=0, le=1440)
    CALENDAR_MAX_EVENTS_DISPLAY: int = Field(default=10, ge=1, le=50)
    CALENDAR_DAYS_AHEAD_DEFAULT: int = Field(default=7, ge=1, le=365)
    
    # =========================================================================
    # DISPLAY LIMITS
    # =========================================================================
    DISPLAY_PROCESSES_COUNT: int = Field(default=10, ge=1, le=50)
    DISPLAY_PROCESSES_VOICE_COUNT: int = Field(default=5, ge=1, le=20)
    DISPLAY_TEMPERATURE_SENSORS_LIMIT: int = Field(default=3, ge=1, le=10)
    DISPLAY_ALERTS_LIMIT: int = Field(default=5, ge=1, le=20)
    
    # =========================================================================
    # VALIDATION CONTROL
    # =========================================================================
    SKIP_CONFIG_VALIDATION: bool = False
    
    # =========================================================================
    # COMPUTED PROPERTIES
    # =========================================================================
    
    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.ENV == "production"
    
    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.ENV == "development"
    
    @property
    def allowed_origins_list(self) -> list[str]:
        """Get CORS allowed origins as a list."""
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]
    
    @property
    def database_is_sqlite(self) -> bool:
        """Check if using SQLite database."""
        return "sqlite" in self.DATABASE_URL.lower()
    
    def get_async_database_url(self) -> str:
        """Get async-compatible database URL."""
        if self.database_is_sqlite:
            return self.DATABASE_URL.replace("sqlite:///", "sqlite+aiosqlite:///")
        # For PostgreSQL, replace psycopg2 with asyncpg
        if "postgresql" in self.DATABASE_URL.lower():
            return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
        return self.DATABASE_URL
    
    def get_system_thresholds(self) -> dict:
        """Get system monitoring thresholds as a dictionary."""
        return {
            "cpu": {
                "warning": self.CPU_WARNING_THRESHOLD,
                "critical": self.CPU_CRITICAL_THRESHOLD,
            },
            "memory": {
                "warning": self.MEMORY_WARNING_THRESHOLD,
                "critical": self.MEMORY_CRITICAL_THRESHOLD,
            },
            "disk": {
                "warning": self.DISK_WARNING_THRESHOLD,
                "critical": self.DISK_CRITICAL_THRESHOLD,
            },
            "battery": {
                "low": self.BATTERY_LOW_THRESHOLD,
                "critical": self.BATTERY_CRITICAL_THRESHOLD,
            },
        }


@lru_cache
def get_settings() -> Settings:
    """
    Get application settings (singleton pattern).
    
    Uses lru_cache to ensure only one Settings instance is created
    and reused throughout the application lifecycle.
    
    Returns:
        Settings: The application settings instance.
    """
    return Settings()


def validate_settings(settings: Settings | None = None) -> dict:
    """
    Validate configuration and return a report.
    
    Args:
        settings: Optional settings instance. Uses get_settings() if not provided.
    
    Returns:
        Dict with validation results including errors and warnings.
    """
    if settings is None:
        settings = get_settings()
    
    errors: list[str] = []
    warnings: list[str] = []
    
    # Check required API keys
    if settings.is_production:
        if not settings.GEMINI_API_KEY:
            errors.append("GEMINI_API_KEY is required in production")
    else:
        if not settings.GEMINI_API_KEY:
            warnings.append("GEMINI_API_KEY not set - AI features will be limited")
    
    # Check threshold consistency
    if settings.CPU_WARNING_THRESHOLD >= settings.CPU_CRITICAL_THRESHOLD:
        warnings.append("CPU_WARNING_THRESHOLD should be less than CPU_CRITICAL_THRESHOLD")
    
    if settings.MEMORY_WARNING_THRESHOLD >= settings.MEMORY_CRITICAL_THRESHOLD:
        warnings.append("MEMORY_WARNING_THRESHOLD should be less than MEMORY_CRITICAL_THRESHOLD")
    
    if settings.DISK_WARNING_THRESHOLD >= settings.DISK_CRITICAL_THRESHOLD:
        warnings.append("DISK_WARNING_THRESHOLD should be less than DISK_CRITICAL_THRESHOLD")
    
    if settings.BATTERY_LOW_THRESHOLD <= settings.BATTERY_CRITICAL_THRESHOLD:
        warnings.append("BATTERY_LOW_THRESHOLD should be greater than BATTERY_CRITICAL_THRESHOLD")
    
    # Check database URL
    if settings.is_production and settings.database_is_sqlite:
        warnings.append("SQLite is not recommended for production use")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }
