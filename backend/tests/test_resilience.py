"""Unit tests for app/core/resilience.py."""

from __future__ import annotations

import pytest

from app.core.resilience import _is_llm_retryable


# ── _is_llm_retryable ─────────────────────────────────────────────────────────

def test_is_llm_retryable_returns_false_for_generic_exception() -> None:
    assert _is_llm_retryable(ValueError("oops")) is False


def test_is_llm_retryable_returns_false_for_runtime_error() -> None:
    assert _is_llm_retryable(RuntimeError("boom")) is False


def test_is_llm_retryable_returns_true_for_anthropic_rate_limit_error() -> None:
    try:
        from anthropic import RateLimitError
    except ImportError:
        pytest.skip("anthropic not installed")

    # RateLimitError requires a response object; we use a minimal mock.
    class FakeResponse:
        status_code = 429
        headers: dict = {}
        request = None

    try:
        exc = RateLimitError("rate limited", response=FakeResponse(), body={})
    except TypeError:
        pytest.skip("RateLimitError constructor signature differs in installed version")

    assert _is_llm_retryable(exc) is True


def test_is_llm_retryable_returns_true_for_anthropic_connection_error() -> None:
    try:
        from anthropic import APIConnectionError
    except ImportError:
        pytest.skip("anthropic not installed")

    class FakeRequest:
        pass

    try:
        exc = APIConnectionError(request=FakeRequest())
    except TypeError:
        pytest.skip("APIConnectionError constructor signature differs in installed version")

    assert _is_llm_retryable(exc) is True


# ── pubmed_retry and llm_retry are tenacity decorators — test they wrap correctly ──

def test_pubmed_retry_decorator_re_raises_after_max_attempts() -> None:
    from http.client import IncompleteRead

    from app.core.resilience import pubmed_retry

    call_count = 0

    @pubmed_retry
    def always_fails():
        nonlocal call_count
        call_count += 1
        raise IncompleteRead(b"partial", 100)

    with pytest.raises(IncompleteRead):
        always_fails()

    # 5 attempts total
    assert call_count == 5


def test_llm_retry_reraises_non_retryable_immediately() -> None:
    from app.core.resilience import llm_retry

    call_count = 0

    @llm_retry
    def non_retryable():
        nonlocal call_count
        call_count += 1
        raise ValueError("not retryable")

    with pytest.raises(ValueError):
        non_retryable()

    # Must not retry non-retryable errors
    assert call_count == 1
