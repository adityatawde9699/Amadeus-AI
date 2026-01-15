"""
Speech/voice adapter implementations.

These adapters wrap the existing speech functionality and implement
the interfaces defined in src/core/interfaces/services.py.
"""

import logging
import os
import tempfile
from typing import Optional

from src.core.config import get_settings
from src.core.exceptions import SpeechRecognitionError, VoiceServiceUnavailableError
from src.core.interfaces.services import IVoiceInput, IVoiceOutput


logger = logging.getLogger(__name__)

# =============================================================================
# DEPENDENCY AVAILABILITY FLAGS
# =============================================================================

AUDIO_DEPS_AVAILABLE = False
MISSING_DEPS = []

try:
    import speech_recognition as sr
    import pyttsx3
    from faster_whisper import WhisperModel
    AUDIO_DEPS_AVAILABLE = True
except ImportError as e:
    MISSING_DEPS.append(str(e))


# =============================================================================
# WHISPER VOICE INPUT ADAPTER
# =============================================================================

class WhisperVoiceInput(IVoiceInput):
    """
    Voice input implementation using Faster-Whisper for transcription.
    
    This adapter wraps the Faster-Whisper model for speech-to-text.
    """
    
    def __init__(self):
        self._model = None
        self._recognizer = None
        self._settings = get_settings()
        self._initialized = False
    
    def _initialize(self) -> None:
        """Lazy initialization of the Whisper model."""
        if self._initialized:
            return
        
        if not AUDIO_DEPS_AVAILABLE:
            logger.warning(f"Audio dependencies not available: {MISSING_DEPS}")
            return
        
        try:
            logger.info(f"Loading Whisper model: {self._settings.WHISPER_MODEL}")
            self._model = WhisperModel(
                self._settings.WHISPER_MODEL,
                device=self._settings.WHISPER_DEVICE,
                compute_type=self._settings.WHISPER_COMPUTE_TYPE,
            )
            self._recognizer = sr.Recognizer()
            self._recognizer.energy_threshold = self._settings.SPEECH_ENERGY_THRESHOLD
            self._recognizer.dynamic_energy_threshold = True
            self._initialized = True
            logger.info("Whisper model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Whisper model: {e}")
            raise VoiceServiceUnavailableError(f"Whisper: {e}")
    
    def is_available(self) -> bool:
        """Check if voice input is available."""
        if not AUDIO_DEPS_AVAILABLE:
            return False
        if not self._settings.VOICE_ENABLED:
            return False
        try:
            self._initialize()
            return self._model is not None
        except Exception:
            return False
    
    def listen(
        self,
        timeout: int | None = None,
        phrase_time_limit: int | None = None
    ) -> str:
        """Listen to microphone and transcribe using Whisper."""
        if not self.is_available():
            raise VoiceServiceUnavailableError("Voice input not available")
        
        timeout = timeout or self._settings.SPEECH_RECOGNITION_TIMEOUT
        phrase_time_limit = phrase_time_limit or self._settings.SPEECH_PHRASE_TIME_LIMIT
        
        with sr.Microphone() as source:
            logger.debug("Listening for speech...")
            
            try:
                audio_data = self._recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
                
                # Skip very short audio
                if len(audio_data.frame_data) < self._settings.SPEECH_MIN_AUDIO_LENGTH:
                    return ""
                
                logger.debug("Processing audio...")
                
                # Save to temp file for Whisper
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                    f.write(audio_data.get_wav_data())
                    temp_path = f.name
                
                try:
                    # Transcribe with Whisper
                    segments, _ = self._model.transcribe(
                        temp_path,
                        beam_size=self._settings.WHISPER_BEAM_SIZE,
                    )
                    text = " ".join(segment.text for segment in segments).strip()
                    
                    if text:
                        logger.debug(f"Transcribed: {text[:50]}...")
                    
                    return text
                finally:
                    os.remove(temp_path)
                    
            except sr.WaitTimeoutError:
                raise SpeechRecognitionError("No speech detected", timeout=True)
            except Exception as e:
                logger.error(f"Speech recognition error: {e}")
                raise SpeechRecognitionError(str(e))


# =============================================================================
# PYTTSX3 VOICE OUTPUT ADAPTER
# =============================================================================

class Pyttsx3VoiceOutput(IVoiceOutput):
    """
    Voice output implementation using pyttsx3 for text-to-speech.
    
    This is a synchronous TTS engine that runs in the main thread.
    For non-blocking speech, use VoiceServiceAdapter instead.
    """
    
    def __init__(self):
        self._engine = None
        self._settings = get_settings()
        self._initialized = False
    
    def _initialize(self) -> None:
        """Lazy initialization of the TTS engine."""
        if self._initialized:
            return
        
        if not AUDIO_DEPS_AVAILABLE:
            logger.warning("pyttsx3 not available")
            return
        
        try:
            self._engine = pyttsx3.init()
            voices = self._engine.getProperty("voices")
            
            # Set voice if available
            if voices:
                voice_idx = min(self._settings.TTS_VOICE_INDEX, len(voices) - 1)
                self._engine.setProperty("voice", voices[voice_idx].id)
            
            self._engine.setProperty("rate", self._settings.TTS_RATE)
            self._initialized = True
            logger.info("TTS engine initialized")
        except Exception as e:
            logger.error(f"Failed to initialize TTS engine: {e}")
    
    def is_available(self) -> bool:
        """Check if voice output is available."""
        if not AUDIO_DEPS_AVAILABLE:
            return False
        if not self._settings.VOICE_ENABLED:
            return False
        try:
            self._initialize()
            return self._engine is not None
        except Exception:
            return False
    
    def speak(self, text: str) -> None:
        """Speak text synchronously."""
        if not text:
            return
        
        if not self.is_available():
            logger.warning(f"[Voice Disabled] {text}")
            return
        
        try:
            # Clean text for TTS (remove emojis etc)
            clean_text = text.encode("ascii", "ignore").decode("ascii")
            self._engine.say(clean_text)
            self._engine.runAndWait()
        except Exception as e:
            logger.error(f"TTS error: {e}")
    
    def speak_async(self, text: str) -> None:
        """
        Speak text asynchronously.
        
        Note: pyttsx3 doesn't support true async. For non-blocking
        speech, use VoiceServiceAdapter with multiprocessing.
        """
        # For this basic adapter, just call sync version
        # Use VoiceServiceAdapter for true async
        self.speak(text)
