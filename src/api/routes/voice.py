"""
Voice WebSocket Route.
Handles real-time audio streaming.
"""

import contextlib
import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from src.app.services.voice_service import VoiceInput, VoiceService
from src.container import get_voice_service


logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/voice")
async def voice_websocket_endpoint(
    websocket: WebSocket, voice_service: VoiceService = Depends(get_voice_service)
) -> None:
    await websocket.accept()
    logger.info("🔌 Voice WebSocket connected")

    try:
        while True:
            # 1. Receive Audio Blob from Client
            audio_data = await websocket.receive_bytes()
            logger.debug("Received audio chunk: %d bytes", len(audio_data))

            # 2. Process
            voice_input = VoiceInput(audio_data=audio_data)
            result = await voice_service.process_audio(voice_input)

            # 3. Send Updates to Client

            # Message 1: Transcription (What server heard)
            await websocket.send_json({"type": "transcription", "text": result.transcript})

            # Message 2: Text Response (What server thought)
            await websocket.send_json({"type": "response_text", "text": result.response_text})

            # Message 3: Audio Response (What server speaks)
            if result.response_audio:
                # Send raw bytes. Client must handle binary message.
                await websocket.send_bytes(result.response_audio)

    except WebSocketDisconnect:
        logger.info("🔌 Voice WebSocket disconnected")
    except Exception as e:
        logger.exception("WebSocket error: %s", e)
        with contextlib.suppress(BaseException):
            await websocket.close()
