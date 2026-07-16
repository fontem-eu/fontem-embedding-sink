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
        # linguistics /embed_batch does BLAS-parallel model.encode() over
        # up to 256 texts at once, so we send the whole batch as one
        # request instead of N sequential (or parallel) /embed hops.
        # Cap per-request to keep pod memory bounded on large batches.
        batch_size = int(os.environ.get("EMBED_BATCH_SIZE", "128"))

        with LinguisticsClient(self._linguistics_url, backend=self._backend) as ling:
            # Pass 1: shape everything cheaply; keep skipped events out.
            work: list[tuple] = []  # (ev, entity_type, entity_id, embed_text, country, event_date)
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
                work.append((ev, entity_type, entity_id, embed_text, country, event_date))

            # Pass 2: batched embed in chunks. Any error in a chunk is
            # re-raised for the normal EventConsumer retry/DLQ path.
            embed_results: list[dict] = []
            for chunk_start in range(0, len(work), batch_size):
                chunk = work[chunk_start:chunk_start + batch_size]
                try:
                    part = ling.embed_batch([w[3] for w in chunk])
                except Exception:
                    ev = chunk[0][0]
                    logger.exception(
                        "linguistics /embed_batch failed near seq=%s (chunk_start=%d, chunk_size=%d)",
                        ev.seq, chunk_start, len(chunk),
                    )
                    raise
                embed_results.extend(part)

            for i, w in enumerate(work):
                _, entity_type, entity_id, embed_text, country, event_date = w
                result = embed_results[i]
                encoder_id = result["encoder_id"]
                if encoder_id not in self._encoder_id_seen:
                    logger.info("using encoder_id=%s", encoder_id)
                    self._encoder_id_seen.add(encoder_id)
                vector_lit = "[" + ",".join(f"{x:.6f}" for x in result["vector"]) + "]"
                rows.append((
                    entity_type, entity_id, encoder_id, embed_text,
                    vector_lit, embed_text,  # embed_text also seeds name_lex
                    country, event_date, w[0].seq,
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
