"""
app/core/resilience.py
----------------------
Retry, backoff, and timeout decorators for all external calls.

Usage:
    @llm_retry
    async def call_llm(...):
        ...

    @pubmed_retry
    def fetch_pubmed_batch(...):
        ...
"""

import logging
from http.client import IncompleteRead, RemoteDisconnected

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

logger = logging.getLogger(__name__)


# ── LLM call retry ──────────────────────────────────────────────────────────
# Handles Anthropic SDK transient errors: rate limits, connection drops, timeouts.
# 4 attempts with exponential backoff: 2s, 4s, 8s, 16s (capped at 30s).

def _is_llm_retryable(exc: BaseException) -> bool:
    """Return True for transient LLM API errors worth retrying."""
    # Import here to avoid hard dependency if anthropic not installed
    try:
        from anthropic import RateLimitError, APIConnectionError, APITimeoutError
        return isinstance(exc, (RateLimitError, APIConnectionError, APITimeoutError))
    except ImportError:
        return False


llm_retry = retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(Exception),  # refined by _is_llm_retryable check inside
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)

# ── PubMed / NCBI Entrez retry ───────────────────────────────────────────────
# 5 attempts. NCBI connections can drop mid-stream on large batches.

pubmed_retry = retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception_type((IncompleteRead, RemoteDisconnected, OSError, Exception)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)

# ── Generic HTTP retry ────────────────────────────────────────────────────────
# For any httpx-based external call.

http_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
