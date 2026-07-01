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

import contextlib
import secrets
import sys
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


if TYPE_CHECKING:
    from src.core.capability import CapabilityProfile


def get_project_root() -> Path:
    """Resolve project root based on whether it is running as a package or executable."""
    if getattr(sys, "frozen", False):
        # Running as compiled PyInstaller executable
        return Path(sys.executable).parent
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
        with contextlib.suppress(OSError):
            token_path.chmod(0o600)
    except OSError as exc:
        _ipc_logger.exception("Could not persist IPC secret token to %s: %s", token_path, exc)
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
    # Hardware capability tier. "auto" probes RAM/CPU/GPU at startup and gates
    # heavy agentic features (multi-expert orchestration, parallel tools, larger
    # models). Force a tier to exercise/limit features regardless of hardware.
    CAPABILITY_TIER: Literal["auto", "lite", "standard", "power"] = "auto"
    ALLOW_DEBUG_RESPONSES: bool = False  # When true, exposes full stack traces to the API client
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # =========================================================================
    # FEATURE FLAGS (Telegram-first roadmap)
    # Gate optional subsystems so the default local daemon stays small and safe.
    # Behaviour-preserving defaults for the FastAPI host are kept where flipping
    # them would change current behaviour; the rest default to "off/opt-in".
    # =========================================================================
    # FastAPI/admin API host. Kept on by default while `amadeus` still launches
    # FastAPI; the Telegram daemon ignores this flag.
    ENABLE_API: bool = True
    # Optional, higher-risk capabilities — off by default.
    ENABLE_EMAIL: bool = False  # IMAP/SMTP email tools (extra: amadeus-ai[email])
    ENABLE_MCP: bool = False  # Connect MCP servers from config/mcp_servers.yaml (extra: [mcp])
    ENABLE_DOCKER_SANDBOX: bool = False  # Docker-backed code sandbox (extra: [sandbox-docker])
    ENABLE_SYSTEM_TOOLS: bool = True  # System-control tools (default-flip is a later security item)
    ENABLE_PLUGINS: bool = False  # Auto-discover/import tools from the plugins/ directory
    # Background loops — opt-in so an idle daemon stays quiet and cheap.
    ENABLE_PROACTIVE_LOOP: bool = False  # APScheduler proactive checks
    ENABLE_AUTONOMOUS_LOOP: bool = False  # AutonomousObservationLoop
    # Phase 3 — event-driven autonomy. When on, watchers emit events onto the
    # runtime EventBus and a dispatcher wakes the agent. Tier-gated: Lite runs
    # threshold checks only; Standard/Power also enable the file watcher.
    ENABLE_EVENT_WATCHERS: bool = False
    ENABLE_THRESHOLD_WATCHER: bool = True   # system health thresholds (CPU/mem/disk/battery)
    ENABLE_FILE_WATCHER: bool = True        # directory change watcher (Standard+ only)
    # Phase 4 — pause risky tool steps *inside* the graph via LangGraph
    # interrupt(), resuming on approval. Off by default: the tool-executor
    # confirmation gate already provides HITL for the live Telegram path, and
    # in-graph interrupts need a transport that calls AmadeusGraph.aresume().
    ENABLE_INGRAPH_HITL: bool = False
    # Phase 4 — feed compact past tool outcomes back into expert planning.
    ENABLE_REFLECTIVE_LEARNING: bool = True
    # Warm the local GGUF model at startup. Off by default to cut startup RAM/CPU
    # on low-end machines; the first message pays the load cost instead.
    SLM_WARMUP_ON_START: bool = False
    # Run Alembic migrations during host startup. Kept on for the FastAPI host;
    # the Telegram daemon starts with this disabled (migrations are an install step).
    RUN_MIGRATIONS_ON_START: bool = True

    # =========================================================================
    # PROACTIVE OBSERVATION LOOP
    # =========================================================================
    PROACTIVE_MESSAGE_LIMIT_PER_HOUR: int = 3
    PROACTIVE_DRY_RUN: bool = False

    # =========================================================================
    # EVENT WATCHERS (Phase 3)
    # =========================================================================
    # Poll cadences for the watchers. Threshold checks are cheap; the file
    # watcher scans mtimes, so keep its interval modest on the floor tier.
    WATCHER_THRESHOLD_INTERVAL_SECONDS: int = Field(default=120, ge=10, le=3600)
    WATCHER_FILE_INTERVAL_SECONDS: int = Field(default=30, ge=5, le=3600)
    # Directories the file watcher monitors for changes (empty = disabled).
    WATCH_DIRS: list[str] = Field(default_factory=list)
    # Session used for watcher-originated (system) agent invocations.
    WATCHER_EVENT_SESSION_ID: str = "system_default_session"
    # Cap on watcher-triggered agent wake-ups per hour (anti-spam).
    WATCHER_MAX_EVENTS_PER_HOUR: int = Field(default=6, ge=1, le=120)

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

    # Root directory indexed by the workspace semantic search tool
    WORKSPACE_INDEX_ROOT: Path = Field(default_factory=Path.home)

    # AMASPACE — the single source of truth for all generated artifacts
    # (research reports, generated code, exports, execution logs, datasets...).
    # Defaults to <project_root>/AMASPACE (set in validator).
    AMASPACE_DIR: Path | None = Field(default=None)

    @field_validator("AMASPACE_DIR", mode="before")
    @classmethod
    def set_amaspace_dir(cls, v: Path | str | None, info: Any) -> Path:
        """Default AMASPACE_DIR to <project_root>/AMASPACE/ if not provided."""
        if v is None:
            base = info.data.get("BASE_DIR") or Path(__file__).parent.parent.parent
            return Path(base) / "AMASPACE"
        return Path(v)

    # When True, the workspace persistence layer refuses to write artifacts
    # outside AMASPACE (path-traversal / absolute-path containment guard).
    WORKSPACE_ENFORCE_CONTAINMENT: bool = True

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
    SLM_CTX_SIZE: int = 4096
    SLM_QUANTIZE_KV_4BIT: bool = True  # 4-bit KV-cache quantization (cuts KV RAM ~75%)

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

    # Network tuning — increase these if api.telegram.org times out on your network.
    # TELEGRAM_PROXY_URL: optional HTTP/SOCKS5 proxy for regions where Telegram is blocked.
    #   Examples: "http://127.0.0.1:8080"  or  "socks5://user:pass@host:1080"
    TELEGRAM_CONNECT_TIMEOUT: float = Field(default=20.0, ge=1.0, le=120.0)
    TELEGRAM_READ_TIMEOUT: float = Field(default=20.0, ge=1.0, le=120.0)
    TELEGRAM_PROXY_URL: str | None = None
    # How many times start_polling retries before giving up (exponential backoff).
    TELEGRAM_MAX_RETRIES: int = Field(default=3, ge=1, le=10)

    # Conversation-only / command-and-control mode (v5). When True, Telegram is a
    # notification channel only: task results, generated content, research output,
    # logs, and reasoning chains are persisted to AMASPACE and Telegram receives
    # only short status notifications (accepted/started/completed/failed) plus the
    # saved artifact path. Set False to restore the legacy "send everything" reply.
    TELEGRAM_NOTIFICATION_ONLY: bool = True
    # Replies longer than this (chars) are treated as artifact-bearing output:
    # persisted to AMASPACE/exports and replaced with a path notification.
    TELEGRAM_MAX_REPLY_CHARS: int = Field(default=600, ge=80, le=4000)

    # =========================================================================
    # RESEARCH ENGINE
    # =========================================================================
    # Upper bounds keep deep-research runs cheap on the 4GB/no-GPU host.
    RESEARCH_MAX_SUBTOPICS: int = Field(default=5, ge=1, le=12)
    RESEARCH_MAX_SOURCES_PER_QUESTION: int = Field(default=5, ge=1, le=15)
    RESEARCH_FETCH_TIMEOUT: int = Field(default=15, ge=3, le=60)
    RESEARCH_MAX_FETCH_PAGES: int = Field(default=8, ge=0, le=30)
    # Forward per-stage research progress to the chat channel. Off by default so
    # a run produces only "started" + "completed/failed" notifications.
    RESEARCH_PROGRESS_NOTIFICATIONS: bool = False

    # =========================================================================
    # PROACTIVE MESSAGING (Master Users)
    # =========================================================================
    # Comma-separated Telegram chat ids authorised to issue commands. REQUIRED
    # for the Telegram channel: when missing/empty/malformed the channel fails
    # CLOSED (no input is accepted) rather than open. Authorised users run at the
    # STANDARD profile by default.
    MASTER_TELEGRAM_CHAT_ID: str | None = None
    # Subset of authorised chat ids that may run SYSTEM_FULL (host/dev/destructive)
    # tools. Empty means no Telegram user gets full system access — elevation is
    # explicit, never implicit.
    TELEGRAM_ELEVATED_CHAT_IDS: str | None = None
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
    ASSISTANT_VERSION: str = "6.0.0"
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
    # Phase 4.3: per-IP rate limit applied to unauthenticated, abuse-prone auth
    # endpoints (login / register / forgot-password / verify) BEFORE credentials
    # are checked, to blunt credential stuffing and account enumeration.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_AUTH_REQUESTS: int = Field(default=10, ge=1)
    RATE_LIMIT_AUTH_WINDOW_SECONDS: int = Field(default=60, ge=1)
    # Only honor X-Forwarded-For for the client IP when explicitly behind a
    # trusted reverse proxy; otherwise the socket peer is used (unspoofable).
    TRUST_PROXY_HEADERS: bool = False

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
    # Code-execution sandbox backend. "docker" runs untrusted code in a hardened
    # ephemeral container; "disabled" refuses to execute code at all. The former
    # insecure "local"/"auto" (in-process exec) modes were removed — they were
    # trivially escapable. Defaults to "disabled" (fail closed).
    SANDBOX_MODE: Literal["disabled", "docker"] = "disabled"

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
    # TOOL SECURITY
    # =========================================================================
    # When True, tools whose capability metadata was auto-derived (not explicitly
    # declared) are denied execution outside development. Default off so the
    # system keeps working until every tool has audited, explicit metadata.
    STRICT_TOOL_METADATA: bool = False

    # =========================================================================
    # NETWORK EGRESS (SSRF) — Phase 3.1
    # =========================================================================
    # When False (default, fail closed) outbound fetch tools refuse to connect to
    # non-public addresses (loopback, private RFC1918, link-local incl. cloud
    # metadata 169.254.169.254, reserved/multicast). Set True ONLY for local
    # development/testing; it is treated as False in production regardless.
    ALLOW_PRIVATE_NETWORK_FETCH: bool = False

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

    @property
    def amaspace_root(self) -> Path:
        """Resolved AMASPACE root — the single source of truth for artifacts."""
        return self.AMASPACE_DIR or (self.BASE_DIR / "AMASPACE")

    @property
    def capability(self) -> "CapabilityProfile":
        """Resolved hardware capability profile (cached; honours CAPABILITY_TIER)."""
        from src.core.capability import resolve_capability

        return resolve_capability(self.CAPABILITY_TIER)

    @staticmethod
    def _parse_id_allowlist(raw: str | None) -> tuple[frozenset[int], bool]:
        """Parse a comma-separated chat-id allowlist, failing CLOSED.

        Returns ``(ids, valid)``. ``valid`` is True only when the input is
        non-empty and every token parses as an int. A single malformed token
        invalidates the whole allowlist (so a typo can never be interpreted as
        "allow everyone").
        """
        text = (raw or "").strip()
        if not text:
            return frozenset(), False
        ids: set[int] = set()
        for tok in text.split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                ids.add(int(tok))
            except ValueError:
                return frozenset(), False  # malformed → invalid (fail closed)
        return frozenset(ids), bool(ids)

    def parse_telegram_allowlist(self) -> tuple[frozenset[int], bool]:
        """Authorised Telegram chat ids and whether the allowlist is valid."""
        return self._parse_id_allowlist(self.MASTER_TELEGRAM_CHAT_ID)

    def telegram_elevated_ids(self) -> frozenset[int]:
        """Chat ids permitted to run SYSTEM_FULL tools (may be empty)."""
        ids, valid = self._parse_id_allowlist(self.TELEGRAM_ELEVATED_CHAT_IDS)
        return ids if valid else frozenset()


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
            errors.append(
                "ALLOW_DEBUG_RESPONSES must be False in production — "
                "stack traces would leak to API clients. "
                "Set ALLOW_DEBUG_RESPONSES=false in your .env."
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

    # Telegram command channel must be allowlisted (fail closed). A configured
    # bot token without a valid MASTER_TELEGRAM_CHAT_ID would otherwise accept
    # commands from anyone.
    if settings.TELEGRAM_BOT_TOKEN:
        _allowed, _valid = settings.parse_telegram_allowlist()
        if not _valid:
            msg = (
                "TELEGRAM_BOT_TOKEN is set but MASTER_TELEGRAM_CHAT_ID is missing "
                "or malformed — the Telegram channel would accept commands from "
                "anyone. Set a valid comma-separated list of numeric chat ids."
            )
            if settings.is_production:
                errors.append(msg)
            else:
                warnings.append(msg)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }
