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
    ) -> AsyncIterator[str]:
        """
        Streaming completion.
        Yields text tokens as they arrive.
        The caller is responsible for assembling the full text.
        """
        ...
