import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.app.services.amadeus_service import AmadeusService


logger = logging.getLogger(__name__)

router = APIRouter()

# Simple connection manager for WebSockets
class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

manager = ConnectionManager()

@router.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time generative responses.
    Receives JSON containing text, sends back a stream of tokens, optionally with audio chunks.
    """
    await manager.connect(websocket)
    try:
        # We instantiate a service instance for this session.
        # In a real app we'd pull session IDs/auth tokens from query params or headers
        amadeus_service = AmadeusService()
        await amadeus_service.initialize()

        while True:
            # Wait for any message from the client
            data = await websocket.receive_text()

            try:
                payload = json.loads(data)
                user_input = payload.get("text", "")
                session_id = payload.get("session_id", amadeus_service.session_id)
            except json.JSONDecodeError:
                user_input = data
                session_id = amadeus_service.session_id

            if not user_input.strip():
                continue

            logger.info(f"WebSocket received: {user_input} (Session: {session_id})")

            # In Phase 4, ideally AmadeusService supports `.handle_command_stream()`
            # For now, we simulate streaming the existing synchronous `handle_command` block
            # or proxy it if Gemini streaming is available.
            # Here we demonstrate the structural pipeline for streaming tokens:

            # TODO: Future enhancement: modify `AmadeusService._process_command_internal` to use
            # `model.generate_content(..., stream=True)` when called from WebSocket.

            # Temporary bridge: Call standard handle_command
            response_text = await amadeus_service.handle_command(user_input, source="websocket")

            # Simulate streaming words to the client for "typing" effect
            words = response_text.split(" ")
            for word in words:
                await websocket.send_json({"type": "text", "content": word + " "})
                await asyncio.sleep(0.05) # simulate latency of generation

            # Signal completion of this turn
            await websocket.send_json({"type": "done"})

    except WebSocketDisconnect:
        logger.info("Client disconnected from WebSocket.")
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        if websocket in manager.active_connections:
             manager.disconnect(websocket)
