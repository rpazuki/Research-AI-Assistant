import httpx

from evaluation.run_eval import _parse_sse_stream


def test_parse_sse_stream_collects_tokens_sources_and_done_latency() -> None:
    response = httpx.Response(
        200,
        content=(
            'data: {"type":"token","data":"Hello"}\n\n'
            'data: {"type":"token","data":" world"}\n\n'
            'data: {"type":"sources","data":[{"pmid":"123"}]}\n\n'
            'data: {"type":"done","latency_ms":42}\n\n'
        ).encode(),
    )

    answer, sources, latency_ms = _parse_sse_stream(response)

    assert answer == "Hello world"
    assert sources == [{"pmid": "123"}]
    assert latency_ms == 42
