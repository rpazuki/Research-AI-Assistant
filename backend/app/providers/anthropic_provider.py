"""
app/providers/anthropic_provider.py
-------------------------------------
Claude (Anthropic) implementation of LLMProvider.

Uses the official `anthropic` Python SDK.
Handles:
- Streaming via client.messages.stream()
- Rate limit and transient error retries (via resilience decorators)
- Logging of token usage and latency
"""

import time
from collections.abc import AsyncIterator

import anthropic
from anthropic import AsyncAnthropic

from app.core.config import settings
from app.core.logging import log
from app.core.resilience import llm_retry
from app.providers.base import CompletionUsage, LLMProvider


class AnthropicProvider(LLMProvider):
    def __init__(self, model: str, api_key: str) -> None:
        self.model = model
        self._client = AsyncAnthropic(api_key=api_key)

    @llm_retry
    async def complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> tuple[str, CompletionUsage]:
        t0 = time.monotonic()
        response = await self._client.messages.create(
            model=self.model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        text = response.content[0].text if response.content else ""
        usage = CompletionUsage(
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            model=self.model,
        )
        log.info(
            "llm_complete",
            model=self.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            latency_ms=latency_ms,
        )
        return text, usage

    async def stream(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        """
        Yields text chunks as they arrive from the Anthropic streaming API.
        The caller assembles the full response.
        """
        async with self._client.messages.stream(
            model=self.model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ) as stream:
            async for text_chunk in stream.text_stream:
                yield text_chunk
