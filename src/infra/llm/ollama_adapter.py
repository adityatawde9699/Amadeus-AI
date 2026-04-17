"""
Ollama Local LLM Adapter for Amadeus AI.

Connects to a locally running Ollama server (http://localhost:11434) to
run Large Language Models 100% offline — no API keys, no internet required.

Optimized for 4GB RAM machines with Phi-3 Mini as the default model.

Supported models (recommended for low-RAM):
  - phi3:mini          (3.8B, ~2.3 GB RAM) — DEFAULT, best quality/RAM ratio
  - llama3.2:3b        (3B,   ~2.0 GB RAM) — fast, good for chat
  - gemma3:2b          (2B,   ~1.5 GB RAM) — smallest viable option
  - mistral:7b-q4      (7B,   ~4.1 GB RAM) — highest quality, needs 4GB+

Usage:
    adapter = OllamaAdapter(base_url="http://localhost:11434", model="phi3:mini")
    response = await adapter.generate_response(prompt="Hello!", context=None)
"""

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from src.core.exceptions import LLMConnectionError, LLMRateLimitError, LLMResponseError
from src.core.interfaces.llm import LLMAdapter


logger = logging.getLogger(__name__)


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass
class OllamaModel:
    """Metadata for an Ollama model."""

    name: str
    size_bytes: int
    modified_at: str
    digest: str

    @property
    def size_gb(self) -> float:
        return round(self.size_bytes / (1024**3), 2)

    @property
    def display_name(self) -> str:
        return self.name.split(":")[0].title()


@dataclass
class ProgressEvent:
    """Download progress event from Ollama pull."""

    status: str
    completed: int = 0
    total: int = 0
    digest: str = ""

    @property
    def percent(self) -> float:
        if self.total == 0:
            return 0.0
        return round((self.completed / self.total) * 100, 1)


# =============================================================================
# OLLAMA ADAPTER
# =============================================================================


class OllamaAdapter(LLMAdapter):
    """
    Adapter for talking to a locally running Ollama server.

    Designed to be a drop-in first-priority provider in the LLMRouter,
    replacing cloud APIs with 100% local, offline, private inference.

    Features:
    - Async streaming via AsyncIterator[str]
    - Health check with auto-detection
    - Model listing and management
    - Real-time pull progress events
    - Graceful fallback if Ollama is not running
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "phi3:mini",
        timeout: float = 120.0,  # Local inference can be slow on CPU
        context_length: int = 4096,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.context_length = context_length
        self._client: httpx.AsyncClient | None = None
        logger.info("OllamaAdapter initialized: model=%s, url=%s", model, base_url)

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create and reuse an httpx async client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    # =========================================================================
    # HEALTH & AVAILABILITY
    # =========================================================================

    async def is_available(self) -> bool:
        """
        Check if Ollama server is running and the target model is available.

        Returns:
            True if Ollama is up and the model is present locally.
        """
        try:
            client = await self._get_client()
            resp = await client.get("/api/tags", timeout=3.0)
            if resp.status_code != 200:
                return False
            data = resp.json()
            models = [m["name"] for m in data.get("models", [])]
            # Accept partial name match: "phi3:mini" matches "phi3:mini"
            available = any(
                self.model in m or m.startswith(self.model.split(":")[0]) for m in models
            )
            if not available:
                logger.warning(
                    "Ollama running but model '%s' not found. Run: ollama pull %s",
                    self.model,
                    self.model,
                )
            return available
        except (httpx.ConnectError, httpx.TimeoutException):
            logger.info("Ollama not running at %s", self.base_url)
            return False
        except Exception as e:
            logger.debug("Ollama availability check error: %s", type(e).__name__)
            return False

    async def is_server_running(self) -> bool:
        """Check if Ollama server is up (even if model isn't pulled)."""
        try:
            client = await self._get_client()
            resp = await client.get("/", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    # =========================================================================
    # GENERATION
    # =========================================================================

    async def generate_response(
        self,
        prompt: str,
        context: Any = None,
        temperature: float = 0.7,
        max_tokens: int | None = 2048,
    ) -> str:
        """
        Generate a response from the local Ollama model.

        This is the primary interface used by LLMRouter.

        Args:
            prompt: The full prompt string
            context: Unused (kept for interface compatibility with cloud adapters)
            temperature: Creativity (0.0 = deterministic, 1.0 = very creative)
            max_tokens: Maximum tokens to generate

        Returns:
            Generated response text

        Raises:
            LLMRateLimitError: If Ollama is not available
        """
        if not await self.is_server_running():
            raise LLMConnectionError("Ollama", "Ollama server is not running")

        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": self.context_length,
            },
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens

        try:
            client = await self._get_client()
            resp = await client.post("/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            response_text = str(data.get("response", "")).strip()
            logger.debug(
                "Ollama generated %d chars (model=%s, tokens=%d)",
                len(response_text),
                self.model,
                data.get("eval_count", 0),
            )
            return response_text
        except httpx.HTTPStatusError as e:
            logger.exception("Ollama HTTP error: %s", e.response.text)
            if e.response.status_code == 429:
                raise LLMRateLimitError("Ollama") from e
            raise LLMResponseError(f"Ollama HTTP {e.response.status_code}: {e.response.text}") from e
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.exception("Ollama connection failed: %s", type(e).__name__)
            raise LLMConnectionError("Ollama", str(e)) from e
        except Exception as e:
            logger.exception("Ollama generation failed: %s", type(e).__name__)
            raise LLMResponseError(f"Ollama generation failed: {e}") from e

    async def stream_response(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int | None = 2048,
    ) -> AsyncIterator[str]:
        """
        Stream response tokens from Ollama one-by-one.

        Compatible with the SSE streaming route in the API server.

        Yields:
            Individual token strings as they are generated
        """
        if not await self.is_server_running():
            yield "⚠️ Ollama is not running. Please start Ollama and try again."
            return

        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_ctx": self.context_length,
            },
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens

        try:
            client = await self._get_client()
            async with client.stream("POST", "/api/generate", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                        token = chunk.get("response", "")
                        if token:
                            yield token
                        if chunk.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.exception("Ollama stream error: %s", e)
            yield f"\n⚠️ Stream interrupted: {type(e).__name__}"

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = 2048,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        """
        Chat-style endpoint using the /api/chat (multi-turn messages).

        Args:
            messages: List of {"role": "user"/"assistant"/"system", "content": "..."}
            temperature: Generation temperature
            max_tokens: Max tokens to generate
            stream: If True, returns AsyncIterator[str]

        Returns:
            Full response string (or AsyncIterator if stream=True)
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_ctx": self.context_length,
            },
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens

        if stream:
            return self._stream_chat(payload)

        client = await self._get_client()
        resp = await client.post("/api/chat", json=payload)
        resp.raise_for_status()
        return str(resp.json()["message"]["content"])

    async def _stream_chat(self, payload: dict) -> AsyncIterator[str]:
        """Internal streaming chat generator."""
        client = await self._get_client()
        async with client.stream("POST", "/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if chunk.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue

    # =========================================================================
    # MODEL MANAGEMENT
    # =========================================================================

    async def list_models(self) -> list[OllamaModel]:
        """
        List all locally available Ollama models.

        Returns:
            List of OllamaModel objects with name, size, and metadata
        """
        try:
            client = await self._get_client()
            resp = await client.get("/api/tags")
            resp.raise_for_status()
            data = resp.json()
            return [
                OllamaModel(
                    name=m["name"],
                    size_bytes=m.get("size", 0),
                    modified_at=m.get("modified_at", ""),
                    digest=m.get("digest", ""),
                )
                for m in data.get("models", [])
            ]
        except Exception as e:
            logger.exception("Failed to list Ollama models: %s", e)
            return []

    async def pull_model(self, name: str) -> AsyncIterator[ProgressEvent]:
        """
        Download an Ollama model with real-time progress streaming.

        Used by the Model Manager UI to show download progress bars.

        Args:
            name: Model name (e.g. "phi3:mini", "llama3.2:3b")

        Yields:
            ProgressEvent with status, completed bytes, and total bytes
        """
        client = await self._get_client()
        payload = {"name": name, "stream": True}

        try:
            async with client.stream("POST", "/api/pull", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                        yield ProgressEvent(
                            status=chunk.get("status", ""),
                            completed=chunk.get("completed", 0),
                            total=chunk.get("total", 0),
                            digest=chunk.get("digest", ""),
                        )
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.exception("Failed to pull model %s: %s", name, e)
            yield ProgressEvent(status=f"error: {e}")

    async def delete_model(self, name: str) -> bool:
        """
        Delete a local Ollama model to free disk space.

        Args:
            name: Model name to delete

        Returns:
            True if deleted successfully
        """
        try:
            client = await self._get_client()
            resp = await client.request("DELETE", "/api/delete", json={"name": name})
            return resp.status_code == 200
        except Exception as e:
            logger.exception("Failed to delete model %s: %s", name, e)
            return False

    async def get_model_info(self, name: str) -> dict:
        """
        Get detailed info about a specific model (parameters, license, etc.)

        Args:
            name: Model name

        Returns:
            Dict with model details or empty dict on failure
        """
        try:
            client = await self._get_client()
            resp = await client.post("/api/show", json={"name": name})
            resp.raise_for_status()
            result: dict[Any, Any] = resp.json()
            return result
        except Exception:
            return {}

    # =========================================================================
    # LLM ADAPTER INTERFACE METHODS
    # =========================================================================

    def get_provider_name(self) -> str:
        return "Ollama"

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "streaming": True,
            "function_calling": False,
            "vision": False,
            "local": True,
        }

    # =========================================================================
    # RESOURCE MANAGEMENT
    # =========================================================================

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> "OllamaAdapter":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()
