"""
Voice WebSocket Route.
Handles real-time audio streaming.
"""

import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from src.container import get_amadeus_service
from src.app.services.voice_service import VoiceService, VoiceInput

logger = logging.getLogger(__name__)
router = APIRouter()

@router.websocket("/ws/voice")
async def voice_websocket_endpoint(
    websocket: WebSocket,
    amadeus_service = Depends(get_amadeus_service)
):
    await websocket.accept()
    logger.info("🔌 Voice WebSocket connected")
    
    # Initialize service for this connection
    voice_service = VoiceService(amadeus_service)
    
    try:
        while True:
            # 1. Receive Audio Blob from Client
            audio_data = await websocket.receive_bytes()
            logger.debug(f"Received audio chunk: {len(audio_data)} bytes")

            # 2. Process
            voice_input = VoiceInput(audio_data=audio_data)
            result = await voice_service.process_audio(voice_input)

            # 3. Send Updates to Client
            
            # Message 1: Transcription (What server heard)
            await websocket.send_json({
                "type": "transcription",
                "text": result.transcript
            })

            # Message 2: Text Response (What server thought)
            await websocket.send_json({
                "type": "response_text",
                "text": result.response_text
            })

            # Message 3: Audio Response (What server speaks)
            if result.response_audio:
                # Send raw bytes. Client must handle binary message.
                await websocket.send_bytes(result.response_audio)

    except WebSocketDisconnect:
        logger.info("🔌 Voice WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.close()
        except:
            pass
