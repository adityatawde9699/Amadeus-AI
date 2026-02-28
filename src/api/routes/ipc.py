"""
IPC (Inter-Process Communication) routes for the Amadeus System Tray GUI.

These endpoints are designed strictly for internal localhost communication
between the active background Python daemon and the lightweight `pystray`
system tray interface.
"""

import logging
from fastapi import APIRouter, status
from pydantic import BaseModel

from src.core.config import get_settings


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ipc", tags=["IPC"])


class DaemonStatus(BaseModel):
    is_alive: bool
    voice_enabled: bool
    version: str


@router.get("/status", response_model=DaemonStatus, status_code=status.HTTP_200_OK)
async def get_daemon_status() -> DaemonStatus:
    """
    Get the current active status of the Amadeus daemon.
    
    Used by the system tray to ensure the daemon is running and display
    accurate icon states (e.g. mic muted vs unmuted).
    """
    settings = get_settings()
    return DaemonStatus(
        is_alive=True,
        voice_enabled=settings.VOICE_ENABLED,
        version=settings.ASSISTANT_VERSION,
    )


class VoiceToggleResponse(BaseModel):
    voice_enabled: bool
    message: str


@router.post("/voice/toggle", response_model=VoiceToggleResponse, status_code=status.HTTP_200_OK)
async def toggle_voice_activation() -> VoiceToggleResponse:
    """
    Toggle the voice/microphone listening state of the daemon.
    
    Used when the user right-clicks the system tray and selects "Mute Mic"
    or "Unmute Mic". This modifies the running settings state.
    """
    settings = get_settings()
    # In a real daemon this needs to hit the observation loop or global state.
    # For now, we update the settings singleton so subsequent checks see the flip.
    settings.VOICE_ENABLED = not settings.VOICE_ENABLED
    
    action = "unmuted" if settings.VOICE_ENABLED else "muted"
    logger.info(f"IPC Command: Microphone {action} via system tray")
    
    # Optional: trigger a speech blurb via the actual voice service here so
    # the user hears "Microphone muted" audibly.
    
    return VoiceToggleResponse(
        voice_enabled=settings.VOICE_ENABLED,
        message=f"Voice activation {action}"
    )
