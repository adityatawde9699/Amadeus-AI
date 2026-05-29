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

import os
import secrets
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_project_root() -> Path:
    """Resolve project root based on whether it is running as a package or executable."""
    if getattr(sys, "frozen", False):
        # Running as compiled PyInstaller executable
        return Path(os.path.dirname(sys.executable))
    # Running as standard Python script
    return Path(__file__).resolve().parent.parent.parent


def load_or_create_ipc_secret() -> str:
    """Load the stable IPC token, creating it once with restricted permissions.

    DR-05: Handles corrupt/unreadable token files gracefully by logging a
    CRITICAL warning before regenerating so operators know that any connected
    IPC clients (system tray, GUI) will need to re-authenticate.
    """
    import logging as _logging
    _ipc_logger = _logging.getLogger(__name__)

    token_path = get_project_root() / "data" / "ipc_secret.token"
    token_path.parent.mkdir(parents=True, exist_ok=True)

    if token_path.exists():
        try:
            token = token_path.read_text(encoding="utf-8").strip()
            if token:
                return token
            # File exists but is empty
            _ipc_logger.critical(
                "IPC secret token file is empty (%s). "
                "Regenerating — connected IPC clients will need to re-authenticate.",
                token_path,
            )
        except UnicodeDecodeError:
            _ipc_logger.critical(
                "IPC secret token file is corrupt / not UTF-8 (%s). "
                "Regenerating — connected IPC clients will need to re-authenticate.",
                token_path,
            )
        except OSError as exc:
            _ipc_logger.critical(
                "Cannot read IPC secret token file (%s): %s. "
                "Regenerating — connected IPC clients will need to re-authenticate.",
                token_path, exc,
            )

    token = secrets.token_hex(32)
    try:
        token_path.write_text(token, encoding="utf-8")
        try:
            os.chmod(token_path, 0o600)
        except OSError:
            pass
    except OSError as exc:
        _ipc_logger.error("Could not persist IPC secret token to %s: %s", token_path, exc)
    return token


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
    DEBUG: bool = False
    ALLOW_DEBUG_RESPONSES: bool = False  # When true, exposes full stack traces to the API client
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # =========================================================================
    # PROACTIVE OBSERVATION LOOP
    # =========================================================================
    PROACTIVE_MESSAGE_LIMIT_PER_HOUR: int = 3
    PROACTIVE_DRY_RUN: bool = False

    # =========================================================================
    # PATHS
    # =========================================================================
    BASE_DIR: Path = Field(default_factory=get_project_root)
    DATA_DIR: Path | None = Field(default=None)  # Will be set in validator

    @field_validator("DATA_DIR", mode="before")
    @classmethod
    def set_data_dir(cls, v: Path | str | None, info: Any) -> Path:
        """Set DATA_DIR relative to BASE_DIR if not provided."""
        if v is None:
            base = info.data.get("BASE_DIR") or Path(__file__).parent.parent.parent
            return Path(base) / "data"
        return Path(v)

    # =========================================================================
    # API KEYS
    # =========================================================================
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-3-flash-preview"
    WEATHER_API_KEY: str | None = None
    NEWS_API_KEY: str | None = None

    # Groq LLM (free tier: 14,400 req/day)
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # =========================================================================
    # LOCAL LLM (SLM) — Primary providers for offline/desktop mode
    # Optimized defaults for low RAM machines
    # =========================================================================
    # When True: ONLY use local offline providers, disable all cloud providers
    LOCAL_ONLY_MODE: bool = True

    # SLM / llama_cpp Settings (Primary if SLM_MODEL_PATH is set)
    SLM_MODEL_PATH: str | None = None  # Absolute path to .gguf file (takes priority)
    SLM_THREADS: int = 2
    SLM_CTX_SIZE: int = 2048

    # =========================================================================
    # MODEL DIRECTORY & AUTO-DOWNLOAD
    # All local models live under MODEL_DIR (defaults to <project>/Model/).
    # Set MODEL_DOWNLOAD_ENABLED=True to auto-fetch missing models on startup.
    # =========================================================================
    MODEL_DIR: Path | None = None  # Defaults to BASE_DIR/Model (set in validator)

    @field_validator("MODEL_DIR", mode="before")
    @classmethod
    def set_model_dir(cls, v: Path | str | None, info: Any) -> Path:
        """Default MODEL_DIR to <project_root>/Model/"""
        if v is None:
            base = info.data.get("BASE_DIR") or Path(__file__).parent.parent.parent
            return Path(base) / "Model"
        return Path(v)

    MODEL_DOWNLOAD_ENABLED: bool = True  # Download missing models on first run

    # Embedding model (sentence-transformers compatible)
    EMBED_MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"
    # If set, caches model to MODEL_DIR/<embed subdir>; otherwise uses HF cache
    EMBED_MODEL_LOCAL_DIR: str | None = None  # Auto-resolved from MODEL_DIR if blank

    # GGUF LLM model — used when SLM_MODEL_PATH is not given
    # Repo and filename on HuggingFace, e.g.:
    #   SLM_MODEL_REPO_ID=bartowski/Llama-3.2-1B-Instruct-GGUF
    #   SLM_MODEL_FILENAME=Llama-3.2-1B-Instruct-Q4_K_M.gguf
    SLM_MODEL_REPO_ID: str | None = None
    SLM_MODEL_FILENAME: str | None = None  # exact filename inside the repo

    # Search APIs
    TAVILY_API_KEY: str | None = None

    # =========================================================================
    # SECURITY
    # =========================================================================
    SECRET_KEY: str | None = None  # Required for JWT auth in production

    # Loaded from env when provided; otherwise generated once and persisted.
    IPC_SECRET_TOKEN: str = Field(default_factory=load_or_create_ipc_secret)

    # =========================================================================
    # OBSERVABILITY
    # =========================================================================
    SENTRY_DSN: str | None = None

    # =========================================================================
    # MESSAGING: TELEGRAM
    # =========================================================================
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_WEBHOOK_SECRET: str | None = None
    TELEGRAM_WEBHOOK_URL: str | None = None  # e.g. https://yourhost.com/api/v1/messaging/telegram

    # =========================================================================
    # PROACTIVE MESSAGING (Master Users)
    # =========================================================================
    MASTER_TELEGRAM_CHAT_ID: str | None = None
    PROACTIVE_CHECK_INTERVAL_MINUTES: int = Field(default=30, ge=1, le=1440)

    # =========================================================================
    # EMAIL (IMAP / SMTP)
    # =========================================================================
    EMAIL_IMAP_SERVER: str = "imap.gmail.com"
    EMAIL_SMTP_SERVER: str = "smtp.gmail.com"
    EMAIL_SMTP_PORT: int = Field(default=587, ge=1, le=65535)
    EMAIL_ADDRESS: str | None = None
    EMAIL_APP_PASSWORD: str | None = None  # App-specific password or OAuth token

    # =========================================================================
    # MEMORY / SUMMARIZATION
    # =========================================================================
    MEMORY_SUMMARIZATION_THRESHOLD: int = Field(default=10, ge=3, le=100)

    # Vector / Long-term semantic memory (Qdrant)
    MEMORY_ENABLED: bool = True
    MEMORY_PERSIST_DIR: str = "./data/vector_db"
    MEMORY_COLLECTION_NAME: str = "amadeus_memory"
    MEMORY_EMBED_MODEL: str = "models/embedding-001"  # Gemini embedding model
    SEMANTIC_ROUTER_THRESHOLD: float = Field(default=0.30, ge=0.0, le=1.0)

    # =========================================================================
    # DATABASE
    # =========================================================================
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/amadeus"
    REDIS_URL: str = "redis://localhost:6379/0"

    # Connection Pool Settings
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=50)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0, le=100)
    DB_POOL_TIMEOUT: int = Field(default=30, ge=1, le=300)
    DB_POOL_RECYCLE: int = Field(default=3600, ge=60)
    DB_ECHO: bool = False

    # =========================================================================
    # ASSISTANT IDENTITY
    # =========================================================================
    ASSISTANT_NAME: str = "Amadeus"
    ASSISTANT_VERSION: str = "3.2.2"
    ASSISTANT_PERSONALITY: str = "intelligent, analytical, precise, and slightly sarcastic"
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
    API_HOST: str = "127.0.0.1"  # Loopback-only when running as desktop app
    API_PORT: int = Field(default=8765, ge=1, le=65535)  # 8765 = Amadeus desktop port
    API_WORKERS: int = Field(default=1, ge=1, le=32)
    # Include tauri:// and tauri.localhost for Tauri 2.0 desktop app
    ALLOWED_ORIGINS: str = (
        "http://localhost:3000,http://localhost:8765,tauri://localhost,https://tauri.localhost"
    )

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

    # Directories the search_file tool is allowed to traverse.
    # Hidden directories (names starting with '.') are always excluded.
    # Override via env var: SEARCH_ALLOWED_DIRS=["~/Documents","~/Downloads"]
    SEARCH_ALLOWED_DIRS: list[str] = Field(
        default=["~/Documents", "~/Desktop", "~/Downloads"],
    )

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
    # SANDBOX
    # =========================================================================
    # "docker" for containerized, "local" for multiprocessing, "auto" for auto-detect
    SANDBOX_MODE: Literal["docker", "local", "auto"] = "auto"

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

    def get_system_thresholds(self) -> dict[str, dict[str, int]]:
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

    @property
    def AGENT_WORKSPACE(self) -> Path:
        """Sandboxed workspace directory for file operations."""
        base = self.DATA_DIR or (self.BASE_DIR / "data")
        ws = base / "agent_workspace"
        ws.mkdir(parents=True, exist_ok=True)
        return ws


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


def _get_or_create_secret_key(settings: "Settings") -> str:
    """SEC-06: Return SECRET_KEY, auto-generating an ephemeral one if not configured.

    An ephemeral key means all JWTs are invalidated on restart, which is
    acceptable for development but must be replaced with a persistent key
    in production (set SECRET_KEY in .env or the environment).
    """
    if settings.SECRET_KEY:
        return settings.SECRET_KEY
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "SECRET_KEY is not set — generating an ephemeral key. "
        "All JWT sessions will be invalidated on restart. "
        "Set SECRET_KEY in your .env file for production."
    )
    return secrets.token_hex(32)


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
        if not settings.SECRET_KEY:
            errors.append(
                "SECRET_KEY is required in production (generate with: openssl rand -hex 32)"
            )

        if getattr(settings, "ALLOW_DEBUG_RESPONSES", False):
            warnings.append(
                "SEVERE SECURITY WARNING: ALLOW_DEBUG_RESPONSES is True in production! Full stack traces may leak to clients."
            )
    else:
        if not settings.GEMINI_API_KEY:
            warnings.append("GEMINI_API_KEY not set - AI features will be limited")
        if not settings.SECRET_KEY:
            warnings.append("SECRET_KEY not set - JWT authentication will not work")
        if not settings.GROQ_API_KEY:
            warnings.append("GROQ_API_KEY not set - Groq LLM provider unavailable (free tier)")

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
