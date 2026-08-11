"""
app/providers/base.py
---------------------
Abstract interface that all LLM provider implementations must satisfy.

Adding a new provider:
1. Create a new file, e.g. app/providers/openai_provider.py
2. Implement LLMProvider
3. Register in app/providers/registry.py
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass
class CompletionUsage:
    prompt_tokens: int
    completion_tokens: int
    model: str
    # Prompt-cache accounting. `cached_tokens` being persistently zero across a
    # batch means something upstream is varying the cached prefix — a timestamp in
    # the system prompt is the classic cause — so it is surfaced, not swallowed.
    cached_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass
class LLMStreamChunk:
    text: str | None = None
    usage: CompletionUsage | None = None


@dataclass
class StructuredResult:
    """One schema-validated extraction, with what it cost."""

    data: dict
    usage: CompletionUsage


@dataclass
class BatchRequest:
    """One paper's extraction, queued for the batch API.

    `custom_id` is how the result is matched back to its paper. Batch results
    return in arbitrary order, so nothing may key on position.
    """

    custom_id: str
    system: str
    content: str
    schema: dict
    model: str | None = None
    max_tokens: int = 8192


@dataclass
class BatchStatus:
    id: str
    processing_status: str          # in_progress | canceling | ended
    succeeded: int = 0
    errored: int = 0
    processing: int = 0
    canceled: int = 0
    expired: int = 0

    @property
    def ended(self) -> bool:
        return self.processing_status == "ended"


@dataclass
class BatchResult:
    custom_id: str
    status: str                     # succeeded | errored | canceled | expired
    data: dict | None = None
    usage: CompletionUsage | None = None
    error: str | None = None


class LLMProvider(ABC):
    """Abstract LLM provider interface."""

    @abstractmethod
    async def complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> tuple[str, CompletionUsage]:
        """
        Non-streaming completion.
        Returns (response_text, usage).
        """
        ...

    @abstractmethod
    async def stream(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> AsyncIterator[str | LLMStreamChunk]:
        """
        Streaming completion. Yields text tokens as they arrive and may yield a
        final usage chunk when the provider exposes stream token accounting.
        """
        ...

    # ── Structured extraction (datasheet round 2) ────────────────────────────
    # Not abstract: a provider that cannot enforce a schema should fail loudly at
    # the call site rather than force every provider to grow a stub. The registry
    # stays the single switch point.

    async def count_prompt_tokens(
        self, *, system: str, content: str, model: str | None = None
    ) -> int:
        """Token count for a prompt, measured by the provider's own tokeniser.

        This is what makes the dry-run cost projection arithmetic rather than a
        guess — character-ratio estimates are wrong by enough to matter across
        several hundred papers.
        """
        raise NotImplementedError(f"{type(self).__name__} cannot count tokens")

    async def extract_structured(
        self,
        *,
        system: str,
        content: str,
        schema: dict,
        max_tokens: int = 8192,
        model: str | None = None,
    ) -> StructuredResult:
        """One schema-constrained call. The provider validates against `schema`."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support structured output"
        )

    async def submit_batch(self, requests: list[BatchRequest]) -> str:
        """Queue a batch and return its id."""
        raise NotImplementedError(f"{type(self).__name__} does not support batching")

    async def poll_batch(self, batch_id: str) -> BatchStatus:
        raise NotImplementedError(f"{type(self).__name__} does not support batching")

    async def cancel_batch(self, batch_id: str) -> None:
        """Ask the provider to stop a batch.

        Best-effort by contract, not by implementation shortcut: requests already
        in flight run to completion and are still billed. "Cancelled" here means
        "no further requests will start", never "free".
        """
        raise NotImplementedError(f"{type(self).__name__} does not support batching")

    def fetch_batch_results(self, batch_id: str) -> AsyncIterator[BatchResult]:
        """Stream results. Keyed by `custom_id` — never by position."""
        raise NotImplementedError(f"{type(self).__name__} does not support batching")
