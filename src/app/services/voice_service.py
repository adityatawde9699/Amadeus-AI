
import logging
import os
import tempfile
from dataclasses import dataclass
from src.app.services.amadeus_service import AmadeusService
from src.infra.speech.adapters import WhisperVoiceInput, Pyttsx3VoiceOutput

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
    def __init__(self, amadeus_service: AmadeusService):
        self.amadeus = amadeus_service
        self.stt = WhisperVoiceInput()
        self.tts = Pyttsx3VoiceOutput()

    async def process_audio(self, voice_input: VoiceInput) -> VoiceResponse:
        # 1. Transcribe (Bytes -> Wav File -> Text)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            f.write(voice_input.audio_data)
            temp_path = f.name
        
        transcript = self.stt.transcribe(temp_path)
        os.remove(temp_path)

        if not transcript.strip():
            return VoiceResponse("", "I couldn't hear you.", None, self.amadeus.session_id)

        # 2. AI Processing
        response_text = await self.amadeus.handle_command(transcript, source="voice")

        # 3. TTS (Text -> Bytes)
        audio_bytes = self.tts.synthesize_to_bytes(response_text)

        return VoiceResponse(transcript, response_text, audio_bytes, self.amadeus.session_id)
