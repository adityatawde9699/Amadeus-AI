import logging
import os
import tempfile
import pyttsx3
from typing import ClassVar, Any
from src.core.config import get_settings

logger = logging.getLogger(__name__)

# Try to import faster_whisper, handle missing package
try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    logger.warning("⚠️ faster-whisper not installed. Voice input will use fallback (Mock).")

class WhisperVoiceInput:
    """STT Adapter: Loads model ONCE (Singleton) to prevent lag."""
    _model_cache: ClassVar[Any | None] = None

    def __init__(self):
        self.settings = get_settings()
        # Initialize only if package is available and not already loaded
        if WHISPER_AVAILABLE and WhisperVoiceInput._model_cache is None:
            self._initialize_model()

    def _initialize_model(self):
        logger.info("⏳ Loading Whisper model...")
        try:
            # FIXED: Use WHISPER_DEVICE instead of undefined USE_GPU
            device = self.settings.WHISPER_DEVICE
            WhisperVoiceInput._model_cache = WhisperModel(
                self.settings.WHISPER_MODEL or "tiny", 
                device=device, 
                compute_type="int8"
            )
            logger.info(f"✅ Whisper model loaded on {device}")
        except Exception as e:
            logger.error(f"Failed to load Whisper: {e}")
            # Keep cache as None to trigger fallback

    def transcribe(self, audio_path: str) -> str:
        # Fallback if module missing OR model failed to load (e.g. DLL error)
        if not WHISPER_AVAILABLE or WhisperVoiceInput._model_cache is None:
            logger.warning("🎤 [Fallback] Whisper unavailable/failed. Using Mock.")
            return "Hello Amadeus, what time is it?"
            
        try:
            segments, _ = WhisperVoiceInput._model_cache.transcribe(audio_path)
            return " ".join(s.text for s in segments).strip()
        except Exception as e:
            logger.error(f"Transcription error: {e}"); return ""

class Pyttsx3VoiceOutput:
    """TTS Adapter: Returns BYTES, does not play audio."""
    def synthesize_to_bytes(self, text: str) -> bytes | None:
        temp_path = tempfile.mktemp(suffix=".wav")
        try:
            engine = pyttsx3.init()
            engine.save_to_file(text, temp_path)
            engine.runAndWait()
            with open(temp_path, "rb") as f: return f.read()
        except Exception as e:
            logger.error(f"TTS error: {e}"); return None
        finally:
            if os.path.exists(temp_path): os.remove(temp_path)
