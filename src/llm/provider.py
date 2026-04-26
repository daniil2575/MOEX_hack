"""Async LLM abstraction returning Pydantic-validated structured output.

Two-tier retry policy:
- Tenacity (outer): transient network errors → exponential backoff, N attempts
- Instructor (inner): Pydantic parse errors → 1 repair-prompt retry

Fallback to slow-path / fallback model is the agent's responsibility — provider
just raises `LLMProviderError` after retries are exhausted.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

import httpx
import instructor
from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import BaseModel
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

T = TypeVar("T", bound=BaseModel)

_RETRYABLE_ERRORS: tuple[type[Exception], ...] = (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    httpx.TimeoutException,
    httpx.ConnectError,
)


class LLMProviderError(Exception):
    """Raised when the LLM call fails after all retries."""


class LLMProvider(ABC):
    """Async LLM provider returning Pydantic-validated structured output."""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        response_model: type[T],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> T: ...


class OpenRouterAdapter(LLMProvider):
    """OpenRouter (OpenAI-compatible) via Instructor for structured output."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: float = 30.0,
        max_retries: int = 3,
        instructor_max_retries: int = 1,
    ) -> None:
        self._model = model
        self._max_retries = max_retries
        self._instructor_max_retries = instructor_max_retries
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self._client = instructor.from_openai(client, mode=instructor.Mode.JSON)

    async def complete(
        self,
        prompt: str,
        response_model: type[T],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> T:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(_RETRYABLE_ERRORS),
            reraise=True,
        ):
            with attempt:
                try:
                    return await self._client.chat.completions.create(
                        model=self._model,
                        messages=[{"role": "user", "content": prompt}],
                        response_model=response_model,
                        max_retries=self._instructor_max_retries,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                except _RETRYABLE_ERRORS:
                    raise
                except APIError as e:
                    raise LLMProviderError(f"OpenRouter API error: {e}") from e
        raise LLMProviderError("retry loop exhausted without result")
