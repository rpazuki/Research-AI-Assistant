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

from anthropic import AsyncAnthropic

from app.core.logging import log
from app.core.resilience import llm_retry
from app.providers.base import CompletionUsage, LLMProvider, LLMStreamChunk


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

    @llm_retry
    async def stream(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> AsyncIterator[str | LLMStreamChunk]:
        """
        Yields text chunks as they arrive from the Anthropic streaming API, then
        emits a final usage chunk with input/output token counts.
        """
        t0 = time.monotonic()
        async with self._client.messages.stream(
            model=self.model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ) as stream:
            async for text_chunk in stream.text_stream:
                yield text_chunk
            final_message = await stream.get_final_message()

        usage = CompletionUsage(
            prompt_tokens=final_message.usage.input_tokens,
            completion_tokens=final_message.usage.output_tokens,
            model=self.model,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        log.info(
            "llm_stream",
            model=self.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            latency_ms=latency_ms,
        )
        yield LLMStreamChunk(usage=usage)
