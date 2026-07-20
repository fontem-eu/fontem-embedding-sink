"""Batch-flow tests for EmbeddingSink.handle with a fake linguistics
client and a fake DB — no network, no Postgres."""
from __future__ import annotations

import logging

import pytest
from fontem_event_schemas import EventEnvelope
from fontem_events.consumer import ConsumerConfig

import embedding_sink.sink as sink_mod
from embedding_sink.sink import EmbeddingSink

ENCODER = "minilm@1.0.0-test"


class FakeLinguistics:
    """Stands in for LinguisticsClient; records embed_batch calls."""

    instances: list["FakeLinguistics"] = []

    def __init__(self, base_url, backend="minilm-local", **_kw):
        self.base_url = base_url
        self.backend = backend
        self.batch_calls: list[list[str]] = []
        FakeLinguistics.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def embed_batch(self, texts):
        """Return one deterministic 2-d vector per text."""
        self.batch_calls.append(list(texts))
        return [
            {"vector": [0.1, 0.2], "dim": 2, "encoder_id": ENCODER, "cached": False}
            for _ in texts
        ]


class FakeCursor:
    """Records executemany(sql, rows) into the shared store."""

    def __init__(self, store):
        self._store = store

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def executemany(self, sql, rows):
        """Capture the statement and its rows."""
        self._store.append((sql, list(rows)))


class FakeConn:
    """Context-manager stand-in for psycopg.connect(...)."""

    def __init__(self, store):
        self._store = store

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def cursor(self):
        """Return a recording cursor."""
        return FakeCursor(self._store)


def _envelope(event_type: str, payload: dict, seq: int) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        iri=f"iri:{seq}",
        domain="test",
        op="upsert",
        payload=payload,
        producer="test",
        seq=seq,
    )


@pytest.fixture(name="sink")
def _sink(monkeypatch):
    """EmbeddingSink wired to FakeLinguistics + a recording fake DB.

    Yields (sink, db_store) where db_store collects executemany calls.
    """
    monkeypatch.setenv("EVENTS_DATABASE_URL", "postgresql://fake/fake")
    monkeypatch.setenv("LINGUISTICS_URL", "http://ling.test")
    monkeypatch.setenv("EMBEDDING_BACKEND", "minilm-local")
    monkeypatch.delenv("SEARCH_DATABASE_URL", raising=False)
    monkeypatch.delenv("EMBED_BATCH_SIZE", raising=False)

    FakeLinguistics.instances = []
    monkeypatch.setattr(sink_mod, "LinguisticsClient", FakeLinguistics)

    store: list = []
    monkeypatch.setattr(
        sink_mod.psycopg, "connect", lambda _dsn: FakeConn(store),
    )

    instance = EmbeddingSink(
        ConsumerConfig(name="embedding_sink", dsn="postgresql://fake/fake"),
    )
    return instance, store


def _batch() -> list[EventEnvelope]:
    return [
        _envelope("UpsertCompany",
                  {"gmr_id": "c-1", "name": "Siemens AG", "country": "DE"}, 10),
        _envelope("UpsertContract",
                  {"ted_notice_id": "n-1", "title": "Road works",
                   "country": "PT", "publication_date": "2026-05-01"}, 11),
        # No composer for relationships — must be skipped.
        _envelope("UpsertRelationship", {"from": "a", "to": "b"}, 12),
        # Composer present but empty name — must be skipped.
        _envelope("UpsertCompany", {"gmr_id": "c-2", "name": ""}, 13),
    ]


def test_handle_writes_rows_with_encoder_id_and_counts_skips(sink, caplog):
    """2 embeddable + 2 skipped events → 2 rows, both stamped with the
    encoder_id the linguistics backend returned."""
    instance, store = sink
    with caplog.at_level(logging.INFO, logger="embedding_sink.sink"):
        instance.handle(_batch())

    assert len(store) == 1
    sql, rows = store[0]
    assert "search.entity_embeddings" in sql
    assert len(rows) == 2

    by_id = {(r[0], r[1]): r for r in rows}
    assert set(by_id) == {("company", "c-1"), ("contract", "n-1")}
    for row in rows:
        assert row[2] == ENCODER                      # encoder_id column
        assert row[4] == "[0.100000,0.200000]"        # vector literal
    assert by_id[("contract", "n-1")][7] == "2026-05-01"  # event_date
    # cols [8..10] = nuts, sector, meta; last_seq moved to [11]
    assert by_id[("company", "c-1")][11] == 10

    # Skips are counted and logged.
    assert "2 embedded, 2 skipped" in caplog.text


def test_handle_upserts_on_pk_for_replay_idempotency(sink):
    """Replaying the same batch issues the same PK-upsert — the
    ON CONFLICT (entity_type, entity_id) clause makes redo safe."""
    instance, store = sink
    instance.handle(_batch())
    instance.handle(_batch())

    assert len(store) == 2
    for sql, _rows in store:
        assert "ON CONFLICT (entity_type, entity_id) DO UPDATE" in sql
    # Identical rows both times → replay converges to the same state.
    assert store[0][1] == store[1][1]


def test_handle_all_skipped_batch_never_touches_db(sink):
    """A batch with no embeddable events must not open a DB txn."""
    instance, store = sink
    instance.handle([
        _envelope("UpsertRelationship", {"from": "a", "to": "b"}, 20),
        _envelope("UpsertTaxonomyCode", {"code": "45.2"}, 21),
    ])
    assert store == []
    assert FakeLinguistics.instances[-1].batch_calls == []


def test_handle_chunks_by_embed_batch_size(sink, monkeypatch):
    """EMBED_BATCH_SIZE caps texts per /embed_batch call."""
    instance, store = sink
    monkeypatch.setenv("EMBED_BATCH_SIZE", "1")
    batch = [
        _envelope("UpsertCompany", {"gmr_id": f"c-{i}", "name": f"Co {i}"}, 30 + i)
        for i in range(3)
    ]
    instance.handle(batch)
    ling = FakeLinguistics.instances[-1]
    assert [len(c) for c in ling.batch_calls] == [1, 1, 1]
    assert len(store[0][1]) == 3
