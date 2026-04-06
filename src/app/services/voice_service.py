import logging
from dataclasses import dataclass

from src.app.services.amadeus_service import AmadeusService
from src.core.interfaces.speech_service import ISpeechToTextService, ITextToSpeechService


logger = logging.getLogger(__name__)


@dataclass
class VoiceInput:
    audio_data: bytes
    sample_rate: int = 16000


@dataclass
class VoiceResponse:
    transcript: str
    response_text: str
    response_audio: bytes | None
    session_id: str


class VoiceService:
    """Orchestrates speech recognition, AI processing, and speech synthesis."""

    def __init__(
        self,
        amadeus_service: AmadeusService,
        stt_service: ISpeechToTextService,
        tts_service: ITextToSpeechService,
    ):
        self.amadeus = amadeus_service
        self.stt = stt_service
        self.tts = tts_service

    async def process_audio(self, voice_input: VoiceInput) -> VoiceResponse:
        """
        Process incoming audio, get AI response, and return synthesized audio.
        """
        # 1. Transcribe (Bytes -> Text)
        transcript = await self.stt.transcribe(voice_input.audio_data)

        if not transcript.strip():
            return VoiceResponse("", "I couldn't hear you.", None, self.amadeus.session_id)

        # 2. AI Processing
        response_text = await self.amadeus.handle_command(transcript, source="voice")

        # 3. TTS (Text -> Bytes)
        audio_bytes = await self.tts.synthesize(response_text)

        return VoiceResponse(transcript, response_text, audio_bytes, self.amadeus.session_id)
