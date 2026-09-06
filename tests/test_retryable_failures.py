"""A store outage must never be mistaken for a poison event.

EventConsumer skips an event that fails ``max_attempts`` times in a
row. Nothing re-emits a skipped event, so the entity is never indexed
and search misses it forever. virtuoso_sink lost 4,006 events this way
during the 2026-09-06 shared replay.

This sink depends on two stores that go away independently — the
linguistics service and the search database — and a linguistics
redeploy is routine, so both are pinned here.
"""
# pylint: disable=protected-access,import-outside-toplevel
from unittest.mock import patch

import httpx
import psycopg
import pytest


@pytest.fixture(name="sink")
def _sink(monkeypatch):
    monkeypatch.setenv("EVENTS_DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv("SEARCH_DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv("LINGUISTICS_URL", "http://linguistics.test")
    from embedding_sink.sink import EmbeddingSink

    with patch("embedding_sink.sink.EventConsumer.__init__",
               lambda self, *a, **k: None):
        s = EmbeddingSink.__new__(EmbeddingSink)
        s._search_dsn = "postgresql://x/y"
        s._linguistics_url = "http://linguistics.test"
        s._backend = "labse-local"
        s._encoder_id_seen = set()
    return s


def _status_error(code):
    request = httpx.Request("POST", "http://linguistics.test/embed")
    return httpx.HTTPStatusError(
        str(code), request=request,
        response=httpx.Response(code, request=request))


@pytest.mark.parametrize("exc", [
    httpx.ConnectError("connection refused"),
    httpx.ReadTimeout("timed out"),
    httpx.RemoteProtocolError("server disconnected"),
])
def test_linguistics_transport_failures_are_retryable(sink, exc):
    """Linguistics redeploying is routine; losing the batch to it is
    not an acceptable price."""
    assert sink.is_retryable(exc) is True


@pytest.mark.parametrize("code", [500, 502, 503, 504, 429])
def test_linguistics_server_health_is_retryable(sink, code):
    """5xx is linguistics unhealthy, 429 is it asking us to slow down.
    Neither says anything about the event."""
    assert sink.is_retryable(_status_error(code)) is True


def test_search_database_outage_is_retryable(sink):
    """psycopg raises OperationalError when the search DB is
    unreachable — same story, different store."""
    assert sink.is_retryable(
        psycopg.OperationalError("connection refused")) is True


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_client_errors_stay_poison(sink, code):
    """A 4xx other than 429 is linguistics rejecting THIS payload."""
    assert sink.is_retryable(_status_error(code)) is False


def test_payload_errors_stay_poison(sink):
    """Bad data and bad SQL are the cases the poison-skip exists for."""
    assert sink.is_retryable(psycopg.ProgrammingError("syntax error")) is False
    assert sink.is_retryable(KeyError("gmr_id")) is False
    assert sink.is_retryable(ValueError("bad payload")) is False
