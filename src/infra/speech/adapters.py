import logging
import os
import tempfile
import asyncio
from typing import ClassVar, Any, AsyncGenerator

from src.core.config import get_settings
from src.core.interfaces.speech_service import ITextToSpeechService, ISpeechToTextService

logger = logging.getLogger(__name__)

# Try to import faster_whisper, handle missing package
try:
    from faster_whisper import WhisperModel
    import pyttsx3
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    logger.warning("⚠️ faster-whisper or pyttsx3 not installed. Voice input will use fallback (Mock).")


class WhisperVoiceInput(ISpeechToTextService):
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

    async def transcribe(self, audio_data: bytes, language: str = "en") -> str:
        """
        Convert audio bytes into text.
        We write to a temporary file since whisper expects a file path or numpy array.
        """
        if not WHISPER_AVAILABLE or WhisperVoiceInput._model_cache is None:
            logger.warning("🎤 [Fallback] Whisper unavailable/failed. Using Mock.")
            return "Hello Amadeus, what time is it?"
            
        temp_path = tempfile.mktemp(suffix=".wav")
        try:
            # Write bytes to temp file for faster_whisper
            with open(temp_path, "wb") as f:
                f.write(audio_data)
                
            # Run in executor to avoid blocking the event loop
            loop = asyncio.get_running_loop()
            
            def _transcribe_sync():
                segments, _ = WhisperVoiceInput._model_cache.transcribe(temp_path, language=language)
                return " ".join(s.text for s in segments).strip()
                
            return await loop.run_in_executor(None, _transcribe_sync)
            
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return ""
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
    async def transcribe_stream(self, audio_stream: AsyncGenerator[bytes, None]) -> AsyncGenerator[str, None]:
        # Dummy implementation for streaming since faster_whisper doesn't natively support byte streaming nicely without VAD
        yield "Streaming not fully implemented"


class Pyttsx3VoiceOutput(ITextToSpeechService):
    """TTS Adapter: Returns BYTES, does not play audio."""
    
    async def synthesize(self, text: str, voice_id: str | None = None) -> bytes:
        if not WHISPER_AVAILABLE: # We tied pyttsx3 to similar check
            return b""
            
        temp_path = tempfile.mktemp(suffix=".wav")
        try:
            loop = asyncio.get_running_loop()
            
            def _synthesize_sync():
                engine = pyttsx3.init()
                if voice_id:
                    # simplistic voice setting mapping
                    voices = engine.getProperty('voices')
                    for voice in voices:
                        if voice_id in voice.id:
                            engine.setProperty('voice', voice.id)
                            break
                            
                engine.save_to_file(text, temp_path)
                engine.runAndWait()
                with open(temp_path, "rb") as f:
                    return f.read()
                    
            return await loop.run_in_executor(None, _synthesize_sync)
            
        except Exception as e:
            logger.error(f"TTS error: {e}")
            return b""
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
