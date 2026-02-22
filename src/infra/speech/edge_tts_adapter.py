"""
Microsoft Edge TTS Adapter for Amadeus AI.

Free, high-quality text-to-speech with no rate limits.
Uses the edge-tts library which piggybacks on Microsoft's TTS service.

Key advantages over pyttsx3:
- Works in Docker/Railway containers (no system audio dependencies)
- Much higher voice quality (neural TTS)
- Multiple voices and languages
- Async-native streaming
"""

import io
import logging
from typing import ClassVar

from src.core.interfaces.speech_service import ITextToSpeechService


logger = logging.getLogger(__name__)


class EdgeTTSAdapter(ITextToSpeechService):
    """
    Microsoft Edge TTS adapter — free, unlimited, high quality.

    Uses the edge-tts library to stream audio from Microsoft's TTS service.
    Audio is cached in-memory (keyed by voice+text hash) to avoid redundant calls.
    """

    # In-memory cache: "voice_id:text_hash" -> audio bytes
    _cache: ClassVar[dict[str, bytes]] = {}
    _MAX_CACHE_ENTRIES: int = 200  # Cap memory usage (~200 phrases)

    def __init__(self, voice: str = "en-US-JennyNeural") -> None:
        self.default_voice = voice

    async def synthesize(self, text: str, voice_id: str | None = None) -> bytes:
        """
        Synthesize text to audio bytes using Edge TTS.

        Args:
            text: Text to synthesize
            voice_id: Optional voice override (e.g. "en-GB-SoniaNeural")

        Returns:
            Audio bytes in MP3 format
        """
        if not text or not text.strip():
            return b""

        try:
            import edge_tts
        except ImportError as e:
            logger.error("edge-tts not installed: %s. Run: pip install edge-tts", e)
            return b""

        voice = voice_id or self.default_voice
        cache_key = f"{voice}:{hash(text)}"

        # Return cached result if available
        if cache_key in self._cache:
            logger.debug("TTS cache hit for: %s...", text[:30])
            return self._cache[cache_key]

        try:
            communicate = edge_tts.Communicate(text, voice)
            audio_buffer = io.BytesIO()

            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_buffer.write(chunk["data"])

            audio_bytes = audio_buffer.getvalue()

            if not audio_bytes:
                logger.warning("Edge TTS returned empty audio for text: %s...", text[:30])
                return b""

            # Store in cache (evict oldest if at capacity)
            if len(self._cache) >= self._MAX_CACHE_ENTRIES:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]

            self._cache[cache_key] = audio_bytes
            logger.debug("TTS synthesized %d bytes for: %s...", len(audio_bytes), text[:30])
            return audio_bytes

        except Exception as e:
            logger.error("Edge TTS synthesis failed: %s", type(e).__name__)
            return b""

    @classmethod
    def clear_cache(cls) -> int:
        """Clear the in-memory TTS cache. Returns number of cleared entries."""
        count = len(cls._cache)
        cls._cache.clear()
        return count

    @classmethod
    def cache_size(cls) -> int:
        """Return current number of cached TTS phrases."""
        return len(cls._cache)
