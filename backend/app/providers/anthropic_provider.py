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

import json
import re
import time
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

from app.core.logging import log
from app.core.resilience import llm_retry
from app.providers.base import (
    BatchRequest,
    BatchResult,
    BatchStatus,
    CompletionUsage,
    LLMProvider,
    LLMStreamChunk,
    StructuredResult,
)

_STRUCTURED_MAX_TOKENS = 8192

# Claude 5 removed the sampling parameters. `temperature`, `top_p` and `top_k` are
# rejected with a 400 rather than ignored, so a request built for Sonnet 4.6 does
# not merely behave differently on Sonnet 5 — it fails outright.
#
# The choice is made here rather than at the call sites because the provider is the
# only layer that knows which model a request is bound for. Callers keep passing
# the configured temperature and it is dropped when the target cannot accept it,
# so moving LLM_MODEL to a Claude 5 model is a config change, not a code change.
_SAMPLING_UNSUPPORTED = re.compile(r"-(?:opus|sonnet|haiku|fable)-(?:[5-9]|\d\d)")


def supports_sampling_params(model: str) -> bool:
    """Whether this model still accepts temperature / top_p / top_k."""
    return _SAMPLING_UNSUPPORTED.search(model or "") is None


def sampling_params(model: str, temperature: float | None) -> dict:
    """The sampling arguments to send — for a Claude 5 model, none of them."""
    if temperature is None or not supports_sampling_params(model):
        return {}
    return {"temperature": temperature}


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
            **sampling_params(self.model, temperature),
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
            **sampling_params(self.model, temperature),
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

    # ── Structured extraction (datasheet round 2) ────────────────────────────

    def _extraction_request(
        self, *, system: str, content: str, schema: dict, max_tokens: int, model: str | None
    ) -> dict:
        """The request body shared by the synchronous and batch paths.

        One builder so the two paths cannot drift: a batch whose prefix differs
        from the synchronous one by a single byte silently stops hitting the
        prompt cache, and the only symptom is a larger bill.

        The system prompt carries a `cache_control` breakpoint. It holds the
        instructions plus the template's JSON schema (~2-3k tokens), which is
        identical across every paper in a run and reads at ~0.1x. Per-paper text
        goes in the user turn, after the breakpoint.
        """
        return {
            "model": model or self.model,
            "max_tokens": max_tokens,
            "system": [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": [{"role": "user", "content": content}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }

    @staticmethod
    def _usage_from(response_usage, model: str) -> CompletionUsage:
        return CompletionUsage(
            prompt_tokens=getattr(response_usage, "input_tokens", 0) or 0,
            completion_tokens=getattr(response_usage, "output_tokens", 0) or 0,
            model=model,
            cached_tokens=getattr(response_usage, "cache_read_input_tokens", 0) or 0,
            cache_creation_tokens=getattr(response_usage, "cache_creation_input_tokens", 0) or 0,
        )

    @staticmethod
    def _first_text(content) -> str:
        for block in content or []:
            if getattr(block, "type", None) == "text":
                return block.text
        return ""

    async def count_prompt_tokens(
        self, *, system: str, content: str, model: str | None = None
    ) -> int:
        response = await self._client.messages.count_tokens(
            model=model or self.model,
            system=system,
            messages=[{"role": "user", "content": content}],
        )
        return response.input_tokens

    @llm_retry
    async def extract_structured(
        self,
        *,
        system: str,
        content: str,
        schema: dict,
        max_tokens: int = _STRUCTURED_MAX_TOKENS,
        model: str | None = None,
    ) -> StructuredResult:
        target = model or self.model
        response = await self._client.messages.create(
            **self._extraction_request(
                system=system,
                content=content,
                schema=schema,
                max_tokens=max_tokens,
                model=target,
            )
        )
        # Safety classifiers can decline a request with a 200 and no content, so
        # `content[0]` is not safe to index. A refusal is a result, not a crash.
        if response.stop_reason == "refusal":
            raise ValueError(
                "extraction refused by the model's safety classifiers "
                f"(category={getattr(response.stop_details, 'category', None)})"
            )
        usage = self._usage_from(response.usage, target)
        log.info(
            "llm_extract_structured",
            model=target,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cached_tokens=usage.cached_tokens,
            stop_reason=response.stop_reason,
        )
        return StructuredResult(data=json.loads(self._first_text(response.content)), usage=usage)

    async def submit_batch(self, requests: list[BatchRequest]) -> str:
        batch = await self._client.messages.batches.create(
            requests=[
                {
                    "custom_id": request.custom_id,
                    "params": self._extraction_request(
                        system=request.system,
                        content=request.content,
                        schema=request.schema,
                        max_tokens=request.max_tokens,
                        model=request.model,
                    ),
                }
                for request in requests
            ]
        )
        log.info("llm_batch_submitted", batch_id=batch.id, requests=len(requests))
        return batch.id

    async def poll_batch(self, batch_id: str) -> BatchStatus:
        batch = await self._client.messages.batches.retrieve(batch_id)
        counts = batch.request_counts
        return BatchStatus(
            id=batch.id,
            processing_status=batch.processing_status,
            succeeded=counts.succeeded,
            errored=counts.errored,
            processing=counts.processing,
            canceled=counts.canceled,
            expired=counts.expired,
        )

    async def cancel_batch(self, batch_id: str) -> None:
        """Stop a batch from starting further requests.

        Requests already in flight finish and are still billed, and the batch moves
        to `canceling` before `ended` — so a cancelled run still costs whatever was
        under way when the cancel landed. Results for the requests that did complete
        remain fetchable, which is why the batch id stays on the run.
        """
        await self._client.messages.batches.cancel(batch_id)
        log.info("llm_batch_cancelled", batch_id=batch_id)

    async def fetch_batch_results(self, batch_id: str) -> AsyncIterator[BatchResult]:
        """Yield one result per request, keyed by `custom_id`.

        Results arrive in arbitrary order — the caller must match on `custom_id`,
        never on position.
        """
        async for entry in await self._client.messages.batches.results(batch_id):
            outcome = entry.result
            if outcome.type != "succeeded":
                yield BatchResult(
                    custom_id=entry.custom_id,
                    status=outcome.type,
                    error=str(getattr(outcome, "error", outcome.type)),
                )
                continue

            message = outcome.message
            if message.stop_reason == "refusal":
                yield BatchResult(
                    custom_id=entry.custom_id,
                    status="refused",
                    error="declined by safety classifiers",
                    usage=self._usage_from(message.usage, message.model),
                )
                continue

            try:
                data = json.loads(self._first_text(message.content))
            except (ValueError, TypeError) as exc:
                # Schema-constrained output should always parse; if it does not,
                # this one paper fails rather than the whole batch.
                yield BatchResult(
                    custom_id=entry.custom_id,
                    status="errored",
                    error=f"unparseable structured output: {exc}",
                    usage=self._usage_from(message.usage, message.model),
                )
                continue

            yield BatchResult(
                custom_id=entry.custom_id,
                status="succeeded",
                data=data,
                usage=self._usage_from(message.usage, message.model),
            )
