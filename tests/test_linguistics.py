"""Tests for LinguisticsClient — /embed_batch, order, and the 404
fallback that transparently targets older linguistics deployments."""
from __future__ import annotations

import json

import httpx
import pytest

from embedding_sink.linguistics import LinguisticsClient


def _result(text: str) -> dict:
    """Deterministic fake embed result derived from the text."""
    return {
        "vector": [float(len(text)), 1.0],
        "dim": 2,
        "encoder_id": "minilm@1.0.0-test",
        "cached": False,
    }


@pytest.fixture(name="patch_transport")
def _patch_transport(monkeypatch):
    """Route the client's internal httpx.Client through a MockTransport."""
    def _apply(handler):
        real_client = httpx.Client

        def fake_client(**kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(**kwargs)

        monkeypatch.setattr(httpx, "Client", fake_client)
    return _apply


def test_embed_batch_preserves_order(patch_transport):
    """One /embed_batch POST; results come back in request order."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.url.path == "/embed_batch"
        body = json.loads(request.content)
        return httpx.Response(
            200, json={"results": [_result(t) for t in body["texts"]]},
        )

    patch_transport(handler)
    with LinguisticsClient("http://ling.test") as ling:
        out = ling.embed_batch(["a", "bbb", "cc"])
    assert calls == ["/embed_batch"]
    assert [r["vector"][0] for r in out] == [1.0, 3.0, 2.0]


def test_embed_batch_404_falls_back_to_sequential_embed(patch_transport):
    """Older linguistics deployments have no /embed_batch — the client
    must fall back to per-text /embed and return the same vectors in
    the same order."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/embed_batch":
            return httpx.Response(404, text="not found")
        assert request.url.path == "/embed"
        body = json.loads(request.content)
        return httpx.Response(200, json=_result(body["text"]))

    patch_transport(handler)
    texts = ["alpha", "bb", "cccccc"]
    with LinguisticsClient("http://ling.test") as ling:
        out = ling.embed_batch(texts)
    # 1 batch attempt + one /embed per text, in order.
    assert calls == ["/embed_batch", "/embed", "/embed", "/embed"]
    assert [r["vector"][0] for r in out] == [5.0, 2.0, 6.0]
    assert all(r["encoder_id"] == "minilm@1.0.0-test" for r in out)


def test_embed_batch_raises_on_5xx(patch_transport):
    """Non-404 errors propagate so the consumer's retry/DLQ kicks in."""
    patch_transport(lambda request: httpx.Response(503, text="redeploying"))
    with LinguisticsClient("http://ling.test") as ling:
        with pytest.raises(httpx.HTTPStatusError):
            ling.embed_batch(["a"])


def test_embed_truncates_to_8000_chars(patch_transport):
    """linguistics caps input at 8192; the client truncates to 8000."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen["len"] = len(body["text"])
        return httpx.Response(200, json=_result(body["text"]))

    patch_transport(handler)
    with LinguisticsClient("http://ling.test") as ling:
        ling.embed("x" * 20000)
    assert seen["len"] == 8000
