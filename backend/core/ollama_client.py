"""
Ollama HTTP client — async generate and evict via httpx.

Base URL and timeout are configurable via environment variables.
Model eviction is critical: the 'model' field MUST be included in the
eviction payload, and the response must contain 'done_reason': 'unload'.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)


class OllamaClient:
    """Async HTTP client for the Ollama inference API."""

    def __init__(self) -> None:
        self._base_url = os.getenv("AEGIS_OLLAMA_URL", "http://localhost:11434")
        self._timeout = float(os.getenv("AEGIS_OLLAMA_TIMEOUT_SECONDS", "120"))
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(self._timeout, connect=10.0),
        )
        logger.info(
            "OllamaClient initialised: base_url=%s, timeout=%ss",
            self._base_url,
            self._timeout,
        )

    async def generate(self, model_name: str, payload: dict) -> httpx.Response:
        """
        POST /api/generate with stream=false.

        All fields from the job payload are passed through verbatim.
        The 'model' and 'stream' fields are set/overridden explicitly.
        """
        body = {**payload, "model": model_name, "stream": False}
        response = await self._client.post("/api/generate", json=body)
        return response

    async def evict(self, model_name: str) -> bool:
        """
        Force-unload a model from VRAM by setting keep_alive=0.

        CRITICAL: The 'model' field is mandatory — an empty payload
        silently fails. We validate that the response contains
        'done_reason': 'unload'.

        Returns True if eviction was validated, False otherwise.
        """
        body = {"model": model_name, "keep_alive": 0}
        try:
            response = await self._client.post(
                "/api/generate",
                json=body,
                # Eviction should be fast — use a shorter timeout
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
            data = response.json()

            if data.get("done_reason") == "unload":
                logger.info("Model '%s' evicted successfully", model_name)
                return True
            else:
                logger.warning(
                    "Model '%s' eviction response missing 'done_reason: unload': %s",
                    model_name,
                    data,
                )
                return False
        except Exception:
            logger.exception("Failed to evict model '%s'", model_name)
            return False

    async def health_check(self) -> bool:
        """Simple connectivity test — GET / returns 200 if Ollama is running."""
        try:
            response = await self._client.get(
                "/", timeout=httpx.Timeout(5.0, connect=5.0)
            )
            return response.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()
