import asyncio
import logging
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, ClassVar

from src.core.config import get_settings
from src.core.interfaces.speech_service import ISpeechToTextService, ITextToSpeechService


logger = logging.getLogger(__name__)

# Try to import faster_whisper, handle missing package
try:
    from faster_whisper import WhisperModel

    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    logger.warning("⚠️ faster-whisper not installed. Voice input (STT) will be unavailable.")


class WhisperVoiceInput(ISpeechToTextService):
    """STT Adapter: Loads model ONCE (Singleton) to prevent lag."""

    _model_cache: ClassVar[Any | None] = None

    def __init__(self) -> None:
        self.settings = get_settings()
        # Initialize only if package is available and not already loaded
        if WHISPER_AVAILABLE and WhisperVoiceInput._model_cache is None:
            self._initialize_model()

    def _initialize_model(self) -> None:
        logger.info("⏳ Loading Whisper model...")
        try:
            settings = get_settings()
            device = settings.WHISPER_DEVICE

            # Use tiny.en for drastic memory and CPU improvements on low-spec hardware
            model_name = settings.WHISPER_MODEL or "tiny.en"

            WhisperVoiceInput._model_cache = WhisperModel(
                model_name,
                device=device,
                compute_type="int8",
                num_workers=2,
                cpu_threads=4,
            )
            logger.info("✅ Whisper model '%s' loaded on %s", model_name, device)
        except Exception as e:
            logger.exception("Failed to load Whisper: %s", e)
            # Keep cache as None — transcribe() will raise a clear exception

    async def transcribe(self, audio_data: bytes, language: str = "en") -> str:
        """
        Convert audio bytes into text.
        We write to a temporary file since whisper expects a file path or numpy array.
        """
        if not WHISPER_AVAILABLE or WhisperVoiceInput._model_cache is None:
            raise RuntimeError(
                "STT unavailable: Whisper model not loaded. "
                "Install faster-whisper and ensure model downloaded correctly."
            )

        # Early return for silence / audio too short to transcribe
        settings = get_settings()
        if not audio_data or len(audio_data) < settings.SPEECH_MIN_AUDIO_LENGTH:
            return ""  # Silence — not an error

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name
            f.write(audio_data)

        try:

            # Run in a single-worker executor to limit memory scaling (OOM protection)
            from src.container import global_container

            ml_pool = global_container.ml_thread_pool()

            loop = asyncio.get_running_loop()
            model = WhisperVoiceInput._model_cache
            if model is None:
                raise ValueError("Whisper model not loaded")

            def _transcribe_sync() -> str:
                segments, _ = model.transcribe(temp_path, language=language)
                return " ".join(s.text for s in segments).strip()

            return await loop.run_in_executor(ml_pool, _transcribe_sync)

        except Exception as e:
            logger.exception("Transcription error: %s", e)
            return ""
        finally:
            if Path(temp_path).exists():
                Path(temp_path).unlink()

    async def transcribe_stream(
        self, audio_stream: AsyncGenerator[bytes, None]
    ) -> AsyncGenerator[str, None]:
        """Stub streaming transcription (not natively supported by faster-whisper)."""

        async def _stub() -> AsyncGenerator[str, None]:
            yield "Streaming not fully implemented"

        return _stub()


class _SilentTTSAdapter(ITextToSpeechService):
    """Fallback TTS that returns empty bytes when edge-tts is not installed."""

    async def synthesize(self, text: str, voice_id: str | None = None) -> bytes:
        logger.warning(
            "TTS unavailable: edge-tts not installed. Returning empty bytes. "
            "Install with: pip install edge-tts"
        )
        return b""
