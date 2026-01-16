
import logging
import os
import tempfile
import pyttsx3
from typing import ClassVar
from faster_whisper import WhisperModel
from src.core.config import get_settings

logger = logging.getLogger(__name__)

class WhisperVoiceInput:
    """STT Adapter: Loads model ONCE (Singleton) to prevent lag."""
    _model_cache: ClassVar[WhisperModel | None] = None

    def __init__(self):
        self.settings = get_settings()
        if WhisperVoiceInput._model_cache is None:
            self._initialize_model()

    def _initialize_model(self):
        logger.info("⏳ Loading Whisper model...")
        try:
            device = "cuda" if self.settings.USE_GPU else "cpu"
            WhisperVoiceInput._model_cache = WhisperModel(
                self.settings.WHISPER_MODEL or "tiny", 
                device=device, 
                compute_type="int8"
            )
            logger.info("✅ Whisper model loaded")
        except Exception as e:
            logger.error(f"Failed to load Whisper: {e}")

    def transcribe(self, audio_path: str) -> str:
        if not WhisperVoiceInput._model_cache: return ""
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
