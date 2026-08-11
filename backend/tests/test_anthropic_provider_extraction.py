"""The Anthropic provider's structured-output and batch surface.

The client is faked, so what is asserted is the request this code builds — which
is where the expensive mistakes live: a sampling parameter that 400s on the
extraction models, or a per-paper value in the cached prefix that quietly turns
off prompt caching for a whole run.
"""

import json
from types import SimpleNamespace

import pytest

from app.providers.anthropic_provider import (
    AnthropicProvider,
    sampling_params,
    supports_sampling_params,
)
from app.providers.base import BatchRequest

SCHEMA = {"type": "object", "properties": {"compounds": {"type": "string"}}}


def text_block(payload: dict):
    return SimpleNamespace(type="text", text=json.dumps(payload))


def usage(**overrides):
    data = {
        "input_tokens": 8_000,
        "output_tokens": 1_200,
        "cache_read_input_tokens": 2_300,
        "cache_creation_input_tokens": 0,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []
        self.batches = FakeBatches()
        self.token_calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response

    async def count_tokens(self, **kwargs):
        self.token_calls.append(kwargs)
        return SimpleNamespace(input_tokens=8_350)


class FakeBatches:
    def __init__(self):
        self.created: list[dict] = []
        self.results_payload: list = []
        self.cancelled: list[str] = []

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id="batch_1")

    async def cancel(self, batch_id):
        self.cancelled.append(batch_id)
        return SimpleNamespace(id=batch_id, processing_status="canceling")

    async def retrieve(self, batch_id):
        return SimpleNamespace(
            id=batch_id,
            processing_status="ended",
            request_counts=SimpleNamespace(
                succeeded=1, errored=0, processing=0, canceled=0, expired=0
            ),
        )

    async def results(self, batch_id):
        async def iterator():
            for entry in self.results_payload:
                yield entry

        return iterator()


def make_provider(response=None) -> tuple[AnthropicProvider, FakeMessages]:
    provider = AnthropicProvider(model="claude-sonnet-5", api_key="test")
    messages = FakeMessages(
        response
        or SimpleNamespace(
            content=[text_block({"compounds": "citric acid"})],
            usage=usage(),
            stop_reason="end_turn",
        )
    )
    provider._client = SimpleNamespace(messages=messages)
    return provider, messages


# ── Request shape ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extraction_never_sends_sampling_parameters() -> None:
    """temperature / top_p / top_k were removed from the API on the extraction
    models — sending one is a 400, not a no-op. The extraction request never
    carries them at all; the chat path decides per model (see below)."""
    provider, messages = make_provider()

    await provider.extract_structured(system="sys", content="paper", schema=SCHEMA)

    request = messages.calls[0]
    assert "temperature" not in request
    assert "top_p" not in request
    assert "top_k" not in request


@pytest.mark.asyncio
async def test_the_shared_prefix_carries_a_cache_breakpoint() -> None:
    """The system block is identical across every paper in a run and reads at
    ~0.1x. Per-paper content goes after it."""
    provider, messages = make_provider()

    await provider.extract_structured(system="sys", content="paper", schema=SCHEMA)

    request = messages.calls[0]
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert request["system"][0]["text"] == "sys"
    assert request["messages"][0]["content"] == "paper"


@pytest.mark.asyncio
async def test_the_schema_is_enforced_by_the_provider_not_parsed_loosely() -> None:
    provider, messages = make_provider()

    await provider.extract_structured(system="sys", content="paper", schema=SCHEMA)

    assert messages.calls[0]["output_config"] == {
        "format": {"type": "json_schema", "schema": SCHEMA}
    }


@pytest.mark.asyncio
async def test_the_escalation_model_overrides_the_default_per_call() -> None:
    provider, messages = make_provider()

    await provider.extract_structured(
        system="sys", content="paper", schema=SCHEMA, model="claude-opus-5"
    )

    assert messages.calls[0]["model"] == "claude-opus-5"


@pytest.mark.asyncio
async def test_batch_and_synchronous_paths_build_the_same_body() -> None:
    """A batch whose prefix differs from the synchronous one by a byte stops
    hitting the cache, and the only symptom is a larger bill."""
    provider, messages = make_provider()

    await provider.extract_structured(system="sys", content="paper", schema=SCHEMA)
    await provider.submit_batch(
        [BatchRequest(custom_id="c1", system="sys", content="paper", schema=SCHEMA)]
    )

    sync_body = messages.calls[0]
    batch_body = messages.batches.created[0]["requests"][0]["params"]
    assert batch_body == sync_body


# ── Responses ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_usage_records_cache_reads() -> None:
    """A persistent zero here means something upstream varies the cached prefix."""
    provider, _messages = make_provider()

    result = await provider.extract_structured(system="sys", content="paper", schema=SCHEMA)

    assert result.data == {"compounds": "citric acid"}
    assert result.usage.prompt_tokens == 8_000
    assert result.usage.cached_tokens == 2_300


@pytest.mark.asyncio
async def test_a_refusal_raises_rather_than_indexing_into_empty_content() -> None:
    """Safety classifiers decline with a 200 and no content; content[0] would
    raise IndexError and hide what happened."""
    provider, _messages = make_provider(
        SimpleNamespace(
            content=[], usage=usage(), stop_reason="refusal",
            stop_details=SimpleNamespace(category="cyber"),
        )
    )

    with pytest.raises(ValueError, match="refused"):
        await provider.extract_structured(system="sys", content="paper", schema=SCHEMA)


@pytest.mark.asyncio
async def test_count_prompt_tokens_uses_the_models_own_tokeniser() -> None:
    provider, messages = make_provider()

    count = await provider.count_prompt_tokens(system="sys", content="paper")

    assert count == 8_350
    assert messages.token_calls[0]["model"] == "claude-sonnet-5"


@pytest.mark.asyncio
async def test_batch_results_carry_their_custom_id() -> None:
    provider, messages = make_provider()
    messages.batches.results_payload = [
        SimpleNamespace(
            custom_id="c2",
            result=SimpleNamespace(
                type="succeeded",
                message=SimpleNamespace(
                    content=[text_block({"compounds": "erythritol"})],
                    usage=usage(),
                    stop_reason="end_turn",
                    model="claude-sonnet-5",
                ),
            ),
        )
    ]

    results = [entry async for entry in provider.fetch_batch_results("batch_1")]

    assert results[0].custom_id == "c2"
    assert results[0].data == {"compounds": "erythritol"}
    assert results[0].usage.cached_tokens == 2_300


@pytest.mark.asyncio
async def test_one_errored_entry_does_not_lose_the_rest_of_the_batch() -> None:
    provider, messages = make_provider()
    messages.batches.results_payload = [
        SimpleNamespace(
            custom_id="bad",
            result=SimpleNamespace(type="errored", error="invalid_request"),
        ),
        SimpleNamespace(
            custom_id="ugly",
            result=SimpleNamespace(
                type="succeeded",
                message=SimpleNamespace(
                    content=[SimpleNamespace(type="text", text="not json")],
                    usage=usage(),
                    stop_reason="end_turn",
                    model="claude-sonnet-5",
                ),
            ),
        ),
        SimpleNamespace(
            custom_id="good",
            result=SimpleNamespace(
                type="succeeded",
                message=SimpleNamespace(
                    content=[text_block({"compounds": "citrate"})],
                    usage=usage(),
                    stop_reason="end_turn",
                    model="claude-sonnet-5",
                ),
            ),
        ),
    ]

    results = {entry.custom_id: entry async for entry in provider.fetch_batch_results("b")}

    assert results["bad"].status == "errored"
    assert results["ugly"].status == "errored"
    assert "unparseable" in results["ugly"].error
    assert results["good"].status == "succeeded"


@pytest.mark.asyncio
async def test_a_refused_batch_entry_is_reported_as_refused_not_as_success() -> None:
    provider, messages = make_provider()
    messages.batches.results_payload = [
        SimpleNamespace(
            custom_id="c1",
            result=SimpleNamespace(
                type="succeeded",
                message=SimpleNamespace(
                    content=[], usage=usage(), stop_reason="refusal", model="claude-sonnet-5"
                ),
            ),
        )
    ]

    results = [entry async for entry in provider.fetch_batch_results("b")]

    assert results[0].status == "refused"
    assert results[0].data is None


@pytest.mark.asyncio
async def test_poll_reports_when_the_batch_has_ended() -> None:
    provider, _messages = make_provider()

    status = await provider.poll_batch("batch_1")

    assert status.ended is True
    assert status.succeeded == 1


@pytest.mark.asyncio
async def test_a_batch_can_be_cancelled() -> None:
    """The only thing standing between a cancelled run and paying for every one of
    its requests."""
    provider, messages = make_provider()

    await provider.cancel_batch("batch_1")

    assert messages.batches.cancelled == ["batch_1"]


def test_providers_without_these_capabilities_fail_loudly() -> None:
    """The registry stays the single switch point: a provider that cannot do
    structured output says so rather than silently returning nothing."""
    from app.providers.base import LLMProvider

    class Minimal(LLMProvider):
        async def complete(self, *args, **kwargs):
            return "", None

        async def stream(self, *args, **kwargs):
            yield ""

    provider = Minimal()
    with pytest.raises(NotImplementedError):
        provider.fetch_batch_results("b")


@pytest.mark.asyncio
async def test_a_provider_that_cannot_cancel_says_so_rather_than_pretending() -> None:
    """`cancel_extraction_batch` treats this as "the batch will run and be billed"
    and logs it — which is only possible because it is raised, not swallowed here."""
    from app.providers.base import LLMProvider

    class Minimal(LLMProvider):
        async def complete(self, *args, **kwargs):
            return "", None

        async def stream(self, *args, **kwargs):
            yield ""

    with pytest.raises(NotImplementedError):
        await Minimal().cancel_batch("b")


# ── Sampling parameters by model generation ───────────────────────────────────


def test_claude_5_models_reject_sampling_parameters() -> None:
    """Claude 5 removed temperature / top_p / top_k: sending one is a 400, so the
    chat path would break the moment LLM_MODEL moved to a 5-series model."""
    for model in ("claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-opus-5[1m]"):
        assert supports_sampling_params(model) is False, model


def test_earlier_models_still_accept_them() -> None:
    for model in ("claude-sonnet-4-6", "claude-opus-4-8", "claude-haiku-4-5-20251001"):
        assert supports_sampling_params(model) is True, model


def test_a_future_generation_is_assumed_to_reject_them_too() -> None:
    """Erring this way costs a sampling knob; erring the other way is a 400 on
    every chat request."""
    assert supports_sampling_params("claude-sonnet-6") is False
    assert supports_sampling_params("claude-opus-12") is False


def test_sampling_params_drops_temperature_only_where_it_is_unsupported() -> None:
    assert sampling_params("claude-sonnet-4-6", 0.1) == {"temperature": 0.1}
    assert sampling_params("claude-sonnet-5", 0.1) == {}
    assert sampling_params("claude-sonnet-4-6", None) == {}


@pytest.mark.asyncio
async def test_chat_completion_sends_temperature_on_a_4_series_model() -> None:
    provider, messages = make_provider()
    provider.model = "claude-sonnet-4-6"

    await provider.complete(system="sys", messages=[{"role": "user", "content": "hi"}])

    assert messages.calls[0]["temperature"] == 0.1


@pytest.mark.asyncio
async def test_chat_completion_omits_temperature_on_a_5_series_model() -> None:
    """The fix: moving LLM_MODEL to Claude 5 is a config change, not a code change."""
    provider, messages = make_provider()
    provider.model = "claude-sonnet-5"

    await provider.complete(system="sys", messages=[{"role": "user", "content": "hi"}])

    assert "temperature" not in messages.calls[0]
    assert messages.calls[0]["model"] == "claude-sonnet-5"
