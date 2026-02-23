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
    """Routes TTS requests - FREE TIER ONLY MODE"""

    def __init__(
        self,
        edge_tts: EdgeTTSAdapter,
    ) -> None:
        self.edge = edge_tts

    async def synthesize(self, text: str, voice_id: str | None = None, priority: str = "normal") -> bytes:
        """Route synthesis - EdgeTTS only."""
        if not text:
            return b""

        # Always use EdgeTTS
        return await self.edge.synthesize(text, voice_id)

    def get_usage_report(self) -> dict:
        """Return TTS usage stats."""
        return {
            "edge_tts_cache_size": self.edge.cache_size(),
            "provider": "edge_tts_only",
            "monthly_cost": 0.0,
        }
