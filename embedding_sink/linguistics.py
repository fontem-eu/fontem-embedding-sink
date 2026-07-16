"""Blocking HTTP client for the /embed endpoint.

The linguistics service is soft-required — 503 / timeout is retried by
the EventConsumer's normal error handling, which will DLQ the batch
after `max_attempts`. A whole batch failing isn't rare when linguistics
is redeploying, so we prefer batch-level retry over per-event catch.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class LinguisticsClient:
    base_url: str
    backend: str = "labse-local"  # cheap, multilingual, no per-call cost
    timeout: float = 30.0         # LaBSE first-warm can take 5-10s
    _client: httpx.Client | None = None

    def __enter__(self) -> "LinguisticsClient":
        self._client = httpx.Client(timeout=self.timeout)
        return self

    def __exit__(self, *_exc: Any) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def embed(self, text: str) -> dict:
        """Returns {'vector': [...], 'dim': 768, 'encoder_id': '...', 'cached': bool}."""
        assert self._client is not None, "use as a context manager"
        r = self._client.post(
            f"{self.base_url.rstrip('/')}/embed",
            json={"text": text[:8000], "backend": self.backend},  # linguistics caps at 8192
        )
        r.raise_for_status()
        return r.json()

    def embed_batch(self, texts: list[str]) -> list[dict]:
        """POST /embed_batch — returns list of {vector, dim, encoder_id, cached}.
        Preserves order. Falls back to per-text /embed on 404 so the
        client can transparently target older linguistics deployments."""
        assert self._client is not None, "use as a context manager"
        r = self._client.post(
            f"{self.base_url.rstrip('/')}/embed_batch",
            json={"texts": [t[:8000] for t in texts], "backend": self.backend},
        )
        if r.status_code == 404:
            return [self.embed(t) for t in texts]
        r.raise_for_status()
        body = r.json()
        return body["results"]

