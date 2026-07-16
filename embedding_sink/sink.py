"""EmbeddingSink — projects entity events into search.entity_embeddings.

Not bracketed. Each event either produces exactly one UPSERT into
search.entity_embeddings (for a supported UpsertX event) or is a no-op
(everything else — Relationships, TaxonomyCodes, Filings, Listings,
AssertSameAs, Begin/EndGraphReplace).

Idempotent by construction: the PRIMARY KEY (entity_type, entity_id)
means re-applying the same event overwrites the same row with the
same (or updated) embedding. Consumer offset persistence follows the
normal fontem-events contract (offset row in events.consumer_offsets,
same Postgres txn as the batch work — crash mid-batch = redo, not loss).

The linguistics /embed calls are the single most expensive thing this
sink does — with LaBSE local, ~50ms / call on CPU + network hop, so
~20/s per worker. Batch size defaults to 100 to keep queue draining
smooth without holding a Postgres txn too long.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import psycopg
from fontem_event_schemas import EventEnvelope
from fontem_events import EventConsumer

from .embed_text import COMPOSERS
from .linguistics import LinguisticsClient

logger = logging.getLogger(__name__)


class EmbeddingSink(EventConsumer):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._search_dsn = os.environ.get("SEARCH_DATABASE_URL") \
            or os.environ["EVENTS_DATABASE_URL"]
        self._linguistics_url = os.environ["LINGUISTICS_URL"]
        # Backend is configurable so we can flip to mistral for a re-embed
        # pass without a redeploy. Default is labse-local (free, multilingual).
        self._backend = os.environ.get("EMBEDDING_BACKEND", "labse-local")
        # Cache the encoder_id across a run so a mid-batch model roll is
        # visible in the logs (a change here means every subsequent row
        # in this run got a different encoder — start a re-embed job).
        self._encoder_id_seen: set[str] = set()

    def handle(self, batch: list[EventEnvelope]) -> None:
        rows: list[tuple] = []
        skipped = 0

        with LinguisticsClient(self._linguistics_url, backend=self._backend) as ling:
            for ev in batch:
                composer = COMPOSERS.get(ev.event_type)
                if composer is None:
                    skipped += 1
                    continue
                shaped = composer(ev.payload)
                if shaped is None:
                    skipped += 1
                    continue
                entity_type, entity_id, embed_text, country, event_date = shaped
                try:
                    result = ling.embed(embed_text)
                except Exception:
                    # Let EventConsumer's normal batch-retry/DLQ path handle it.
                    logger.exception(
                        "linguistics /embed failed on seq=%s type=%s id=%s",
                        ev.seq, entity_type, entity_id,
                    )
                    raise
                encoder_id = result["encoder_id"]
                if encoder_id not in self._encoder_id_seen:
                    logger.info("using encoder_id=%s", encoder_id)
                    self._encoder_id_seen.add(encoder_id)
                # pgvector accepts a stringified list: '[0.1, -0.2, ...]'
                vector_lit = "[" + ",".join(f"{x:.6f}" for x in result["vector"]) + "]"
                rows.append((
                    entity_type, entity_id, encoder_id, embed_text,
                    vector_lit, embed_text,  # embed_text also seeds name_lex
                    country, event_date, ev.seq,
                ))

        if not rows:
            if skipped:
                logger.debug("batch of %d events, all skipped (non-embeddable)", skipped)
            return

        # One transaction, one round-trip. copy would be faster but a
        # per-batch UPSERT with executemany is simple and idempotent.
        # tsvector uses `simple` config for now — per-language analyzers
        # come in phase-two once the sink's stable.
        with psycopg.connect(self._search_dsn) as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO search.entity_embeddings
                      (entity_type, entity_id, encoder_id, embed_text,
                       embedding, name_lex, country, event_date, last_seq)
                    VALUES
                      (%s, %s, %s, %s,
                       %s::vector, to_tsvector('simple', %s), %s, %s, %s)
                    ON CONFLICT (entity_type, entity_id) DO UPDATE SET
                      encoder_id = EXCLUDED.encoder_id,
                      embed_text = EXCLUDED.embed_text,
                      embedding  = EXCLUDED.embedding,
                      name_lex   = EXCLUDED.name_lex,
                      country    = EXCLUDED.country,
                      event_date = EXCLUDED.event_date,
                      last_seq   = EXCLUDED.last_seq,
                      updated_at = now()
                    """,
                    rows,
                )

        logger.info(
            "batch: %d embedded, %d skipped (last_seq=%s)",
            len(rows), skipped, batch[-1].seq,
        )
