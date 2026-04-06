"""
Interfaces for Core Speech Services.

Defines abstract base classes for Text-to-Speech (TTS)
and Speech-to-Text (STT) capabilities to decouple implementations
from the core business logic.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator


class ITextToSpeechService(ABC):
    """Abstract interface for text-to-speech services."""

    @abstractmethod
    async def synthesize(self, text: str, voice_id: str | None = None) -> bytes:
        """
        Convert text into raw audio bytes.

        Args:
            text: Text to synthesize
            voice_id: Optional identifier for a specific voice

        Returns:
            Audio data as bytes
        """


class ISpeechToTextService(ABC):
    """Abstract interface for speech-to-text services."""

    @abstractmethod
    async def transcribe(self, audio_data: bytes, language: str = "en") -> str:
        """
        Convert audio bytes into text.

        Args:
            audio_data: Raw audio data
            language: Expected language code

        Returns:
            Transcribed text
        """

    @abstractmethod
    async def transcribe_stream(
        self, audio_stream: AsyncGenerator[bytes, None]
    ) -> AsyncGenerator[str, None]:
        """
        Process a continuous stream of audio into text chunks.

        Args:
            audio_stream: Async generator yielding audio chunks

        Returns:
            Async generator yielding transcribed text chunks
        """
