"""
TTS Request Router for Amadeus AI.

Routes text-to-speech synthesis based on priority and monthly limits:
- Normal priority: EdgeTTS (free, unlimited, high quality)
- Critical priority: ElevenLabs (free tier: 10,000 chars/month, premium quality)

ElevenLabsAdapter is a thin wrapper around the elevenlabs SDK.
"""

import logging

from src.core.interfaces.speech_service import ITextToSpeechService
from src.infra.speech.edge_tts_adapter import EdgeTTSAdapter


logger = logging.getLogger(__name__)


class ElevenLabsAdapter(ITextToSpeechService):
    """
    ElevenLabs TTS adapter — premium quality for critical responses.
    Free tier: 10,000 characters/month.
    """

    def __init__(self, api_key: str, voice_id: str = "21m00Tcm4TlvDq8ikWAM") -> None:
        """
        Args:
            api_key: ElevenLabs API key
            voice_id: ElevenLabs voice ID (default: Rachel)
        """
        self._api_key = api_key
        self._default_voice_id = voice_id

    async def synthesize(self, text: str, voice_id: str | None = None) -> bytes:
        """Synthesize with ElevenLabs — runs blocking SDK call in executor."""
        if not text or not text.strip():
            return b""

        try:
            import asyncio
            from elevenlabs import ElevenLabs

            client = ElevenLabs(api_key=self._api_key)
            target_voice = voice_id or self._default_voice_id

            def _call_elevenlabs() -> bytes:
                audio_generator = client.text_to_speech.convert(
                    voice_id=target_voice,
                    text=text,
                    model_id="eleven_turbo_v2",
                )
                return b"".join(audio_generator)

            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, _call_elevenlabs)

        except ImportError:
            logger.error("elevenlabs package not installed. Run: pip install elevenlabs")
            return b""
        except Exception as e:
            logger.error("ElevenLabs TTS failed: %s", type(e).__name__)
            return b""


class TTSRouter(ITextToSpeechService):
    """
    Routes TTS requests to appropriate provider based on priority and limits.

    Priority routing:
    - Normal: EdgeTTS (free, unlimited)
    - Critical: ElevenLabs → EdgeTTS fallback (if ElevenLabs over limit or unavailable)
    """

    ELEVENLABS_FREE_LIMIT: int = 10_000  # chars/month

    def __init__(
        self,
        edge_tts: EdgeTTSAdapter,
        elevenlabs: ElevenLabsAdapter | None = None,
    ) -> None:
        self.edge = edge_tts
        self.elevenlabs = elevenlabs
        self._elevenlabs_chars_this_month: int = 0

    async def synthesize(self, text: str, voice_id: str | None = None, priority: str = "normal") -> bytes:
        """
        Route synthesis request to best provider.

        Args:
            text: Text to synthesize
            voice_id: Optional voice override
            priority: "normal" (EdgeTTS) or "critical" (try ElevenLabs first)
        """
        if not text:
            return b""

        # Critical priority: attempt ElevenLabs first (within free limit)
        if priority == "critical" and self.elevenlabs:
            chars_needed = len(text)
            if self._elevenlabs_chars_this_month + chars_needed <= self.ELEVENLABS_FREE_LIMIT:
                logger.debug("TTS: routing to ElevenLabs (priority=critical)")
                audio = await self.elevenlabs.synthesize(text, voice_id)
                if audio:
                    self._elevenlabs_chars_this_month += chars_needed
                    return audio
                logger.warning("ElevenLabs returned empty audio, falling back to EdgeTTS")
            else:
                logger.warning(
                    "ElevenLabs monthly limit reached (%d/%d chars). Using EdgeTTS.",
                    self._elevenlabs_chars_this_month,
                    self.ELEVENLABS_FREE_LIMIT,
                )

        # Default: EdgeTTS (always available)
        logger.debug("TTS: routing to EdgeTTS (priority=%s)", priority)
        return await self.edge.synthesize(text, voice_id)

    def get_usage_report(self) -> dict:
        """Return TTS usage stats."""
        return {
            "elevenlabs_chars_used": self._elevenlabs_chars_this_month,
            "elevenlabs_chars_limit": self.ELEVENLABS_FREE_LIMIT,
            "elevenlabs_chars_remaining": max(
                0, self.ELEVENLABS_FREE_LIMIT - self._elevenlabs_chars_this_month
            ),
            "edge_tts_cache_size": self.edge.cache_size(),
            "elevenlabs_configured": self.elevenlabs is not None,
        }
