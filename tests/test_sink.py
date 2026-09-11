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
    """Records executemany(sql, rows) into the shared store, and answers the
    sink's "what does the index already hold" SELECT from `stored_rows`."""

    #: (entity_type, entity_id) -> (parts, embed_text, encoder_id). Set by a
    #: test; empty means every row in the batch is new to the index.
    stored_rows: dict = {}
    selects: list = []

    def __init__(self, store):
        self._store = store
        self._rows: list = []

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def executemany(self, sql, rows):
        """Capture the statement and its rows."""
        self._store.append((sql, list(rows)))

    def execute(self, sql, params=None):
        """Answer the stored-rows lookup. Kept out of the write store so a
        test still reads writes by position."""
        FakeCursor.selects.append((sql, params))
        types, ids = params if params else ([], [])
        self._rows = [(t, i, *FakeCursor.stored_rows[(t, i)])
                      for t, i in zip(types, ids)
                      if (t, i) in FakeCursor.stored_rows]

    def fetchall(self):
        """Rows for the last execute()."""
        return self._rows


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
    FakeCursor.stored_rows = {}
    FakeCursor.selects = []
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


def test_translation_event_writes_name_lex_i18n_only(sink):
    """A TranslateAuthorityName event updates ONLY the name_lex_i18n lane
    (translations), off the embed path — no linguistics call, no
    embed_text/vector/name_lex write. Durable against entity re-loads."""
    instance, store = sink
    batch = [
        _envelope("UpsertAuthority",
                  {"authority_id": "a-1", "name": "Urząd Miasta",
                   "country": "PL", "nuts": "PL91"}, 20),
        _envelope("TranslateAuthorityName",
                  {"authority_id": "a-1", "name": "Urząd Miasta",
                   "source_lang": "pl",
                   "translations": {"de": "Stadtamt", "en": "City Office"}}, 21),
    ]
    instance.handle(batch)

    # Two executemany calls: the i18n UPDATE (pre-pass) + the authority's
    # full upsert. Neither the translation event embeds.
    i18n = [(sql, rows) for sql, rows in store if "name_lex_i18n" in sql]
    assert len(i18n) == 1, "translation must write name_lex_i18n exactly once"
    sql, rows = i18n[0]
    assert "UPDATE search.entity_embeddings" in sql
    # SET only name_lex_i18n (+ updated_at) — nothing else touched
    set_clause = sql.split("SET", 1)[1].split("WHERE", 1)[0]
    for col in ("embed_text", "embedding", "name_lex ", "country", "nuts", "sector", "meta"):
        assert col not in set_clause, f"i18n update must not touch {col}"
    # params are (translations_text, authority_id)
    text, aid = rows[0]
    assert aid == "a-1"
    assert "Stadtamt" in text and "City Office" in text
    # linguistics embed_batch was called only for the 1 authority (not the translation)
    assert len(FakeLinguistics.instances[-1].batch_calls) == 1
    assert sum(len(c) for c in FakeLinguistics.instances[-1].batch_calls) == 1


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
    # cols [8..11] = nuts, sector, meta, parts; last_seq last
    assert by_id[("company", "c-1")][12] == 10

    # Skips are counted and logged.
    assert "2 embedded" in caplog.text and "2 skipped" in caplog.text


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
    # parts rides as a psycopg Json wrapper, which compares by identity.
    def _plain(rows):
        return [tuple(c.obj if hasattr(c, "obj") else c for c in r) for r in rows]
    assert _plain(store[0][1]) == _plain(store[1][1])


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


def test_a_partial_event_keeps_the_context_the_row_already_had(sink):
    """The bug this column exists for. load_ted_contracts states a
    supplier's name and country as one notice spells them; composing the
    row from that slice alone dropped the city, aliases and legal form
    GLEIF had given it, and the vector with them."""
    instance, store = sink
    FakeCursor.stored_rows[("company", "c-9")] = (
        {"gmr_id": "c-9", "name": "Siemens AG", "aliases": ["Siemens"],
         "city": "Munchen", "country": "DEU", "legal_form": "AG", "lei": "L1"},
        "Siemens AG — Siemens — Munchen — DEU — AG", ENCODER,
    )
    instance.handle([_envelope(
        "UpsertCompany",
        {"gmr_id": "c-9", "name": "SIEMENS AKTIENGESELLSCHAFT", "country": "DEU"},
        40)])

    _sql, rows = store[0]
    text = rows[0][3]
    assert "SIEMENS AKTIENGESELLSCHAFT" in text, "a stated value must win"
    for kept in ("Munchen", "AG", "Siemens"):
        assert kept in text, f"{kept} was dropped by a partial event"
    parts = rows[0][11].obj
    assert parts["name"] == "SIEMENS AKTIENGESELLSCHAFT"
    assert parts["city"] == "Munchen" and parts["lei"] == "L1"


def test_a_null_in_the_event_does_not_erase_a_stored_field(sink):
    """Absent and null are both "not stated" — the rule the Neo4j sink
    applies when it builds a node's SET map."""
    instance, store = sink
    FakeCursor.stored_rows[("company", "c-7")] = (
        {"gmr_id": "c-7", "name": "Acme SA", "city": "Lisboa", "country": "PRT"},
        "Acme SA — Lisboa — PRT", ENCODER,
    )
    instance.handle([_envelope(
        "UpsertCompany",
        {"gmr_id": "c-7", "name": "Acme SA", "city": None, "country": "PRT"}, 41)])
    assert store[0][1][0][11].obj["city"] == "Lisboa"


def test_an_unchanged_row_keeps_its_vector(sink):
    """Re-stating a record composes the text the row already has. Embedding
    it again costs a linguistics turn per row and changes nothing — and the
    repair backfills re-state whole records by the million."""
    instance, store = sink
    payload = {"gmr_id": "c-8", "name": "Acme SA", "country": "FRA"}
    instance.handle([_envelope("UpsertCompany", payload, 42)])  # learns the encoder
    text = store[0][1][0][3]

    FakeCursor.stored_rows[("company", "c-8")] = (dict(payload), text, ENCODER)
    store.clear()
    instance.handle([_envelope("UpsertCompany", payload, 43)])

    assert FakeLinguistics.instances[-1].batch_calls == [], "must not re-embed"
    assert len(store) == 1
    sql, rows = store[0]
    assert sql.strip().startswith("UPDATE")
    set_clause = sql.split("SET", 1)[1].split("WHERE", 1)[0]
    for untouched in ("embedding", "embed_text", "name_lex"):
        assert untouched not in set_clause, \
            f"an unchanged row must not rewrite {untouched}"
    assert rows[0][6] == 43                       # last_seq still advances
    assert rows[0][7:] == ("company", "c-8")


def test_a_different_encoder_re_embeds_even_unchanged_text(sink):
    """A re-embed pass (EMBEDDING_BACKEND flipped) must not be skipped by
    the unchanged check: same text, different model, new vector."""
    instance, store = sink
    payload = {"gmr_id": "c-6", "name": "Acme SA", "country": "FRA"}
    instance.handle([_envelope("UpsertCompany", payload, 44)])
    text = store[0][1][0][3]
    FakeCursor.stored_rows[("company", "c-6")] = (dict(payload), text, "labse@old")
    store.clear()
    instance.handle([_envelope("UpsertCompany", payload, 45)])
    assert FakeLinguistics.instances[-1].batch_calls == [[text]]
    assert "INSERT INTO search.entity_embeddings" in store[0][0]
