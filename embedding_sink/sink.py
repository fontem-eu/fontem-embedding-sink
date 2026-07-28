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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import psycopg
from fontem_event_schemas import EventEnvelope
from fontem_events import EventConsumer

from .embed_text import COMPOSERS
from .linguistics import LinguisticsClient

logger = logging.getLogger(__name__)


class EmbeddingSink(EventConsumer):
    """Event consumer that embeds Upsert* events into search.entity_embeddings."""

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

    def _apply_name_lex_i18n(self, rows: list[tuple]) -> None:
        """Update the translations-only lexical lane (name_lex_i18n) for
        authorities. Touches nothing else: Upsert* owns name_lex/embed_text/
        vector, so translations written here can't be clobbered by an
        entity re-load. No re-embedding — the vector adds nothing for
        translated names. Only affects rows that already exist (the
        authority must be in the index first)."""
        with psycopg.connect(self._search_dsn) as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    UPDATE search.entity_embeddings
                    SET name_lex_i18n = to_tsvector('simple', %s),
                        updated_at = now()
                    WHERE entity_type = 'authority' AND entity_id = %s
                    """,
                    rows,
                )
        logger.info("i18n: name_lex_i18n updated for %d authorities", len(rows))

    def handle(self, batch: list[EventEnvelope]) -> None:
        # One long, linear batch pipeline — kept inline on purpose.
        # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        #
        # i18n lexical lane: TranslateAuthorityName enriches name_lex_i18n
        # (translations only) — a column no Upsert* event ever writes, so
        # translations survive entity re-loads. Handled off the embed path
        # (no linguistics call); everything else flows through compose+embed.
        i18n: list[tuple] = []
        for ev in batch:
            if ev.event_type != "TranslateAuthorityName":
                continue
            aid = ev.payload.get("authority_id")
            translations = ev.payload.get("translations") or {}
            text = " ".join(
                str(v).strip() for v in translations.values() if v and str(v).strip()
            )
            if aid and text:
                i18n.append((text, aid))
        if i18n:
            self._apply_name_lex_i18n(i18n)

        rows: list[tuple] = []
        skipped = 0
        # linguistics /embed_batch does BLAS-parallel model.encode() over
        # up to 256 texts at once, so we send the whole batch as one
        # request instead of N sequential (or parallel) /embed hops.
        # Cap per-request to keep pod memory bounded on large batches.
        batch_size = int(os.environ.get("EMBED_BATCH_SIZE", "128"))

        with LinguisticsClient(self._linguistics_url, backend=self._backend) as ling:
            # Pass 1: shape everything cheaply; keep skipped events out.
            # (ev, entity_type, entity_id, embed_text, country, event_date, nuts, sector, meta)
            work: list[tuple] = []
            for ev in batch:
                composer = COMPOSERS.get(ev.event_type)
                if composer is None:
                    skipped += 1
                    continue
                shaped = composer(ev.payload)
                if shaped is None:
                    skipped += 1
                    continue
                entity_type, entity_id, embed_text, country, event_date, nuts, sector, meta = shaped
                work.append((
                    ev, entity_type, entity_id, embed_text, country, event_date,
                    nuts, sector, meta,
                ))

            # Pass 2: batched embed. Chunks sized by EMBED_BATCH_SIZE and
            # dispatched in parallel through a small ThreadPoolExecutor
            # so a single ling pod's spare cores are actually used.
            # Concurrency defaults to 4: linguistics is BLAS-bound per
            # batch, so a handful of concurrent chunks saturates one pod
            # without over-queuing.
            chunk_workers = int(os.environ.get("EMBED_BATCH_CONCURRENCY", "4"))
            chunks = [work[i:i + batch_size] for i in range(0, len(work), batch_size)]
            embed_results: list[dict] = [None] * len(work)  # type: ignore[list-item]
            first_exc: BaseException | None = None
            failed_chunk_idx: int | None = None
            if chunks:
                with ThreadPoolExecutor(max_workers=chunk_workers) as pool:
                    fut_meta = {
                        pool.submit(ling.embed_batch, [w[3] for w in chunk]): (ci, chunk)
                        for ci, chunk in enumerate(chunks)
                    }
                    for fut in as_completed(fut_meta):
                        ci, chunk = fut_meta[fut]
                        try:
                            part = fut.result()
                        except Exception as exc:  # noqa: BLE001  pylint: disable=broad-exception-caught
                            if first_exc is None:
                                first_exc = exc
                                failed_chunk_idx = ci
                            continue
                        base = ci * batch_size
                        for j, r in enumerate(part):
                            embed_results[base + j] = r
            if first_exc is not None:
                first_ev = chunks[failed_chunk_idx][0][0]
                logger.exception(
                    "linguistics /embed_batch failed near seq=%s (chunk_idx=%d)",
                    first_ev.seq, failed_chunk_idx,
                )
                raise first_exc

            for i, w in enumerate(work):
                _, entity_type, entity_id, embed_text, country, event_date, nuts, sector, meta = w
                result = embed_results[i]
                encoder_id = result["encoder_id"]
                if encoder_id not in self._encoder_id_seen:
                    logger.info("using encoder_id=%s", encoder_id)
                    self._encoder_id_seen.add(encoder_id)
                vector_lit = "[" + ",".join(f"{x:.6f}" for x in result["vector"]) + "]"
                # psycopg serialises dicts to jsonb via Json adapter; import lazily to avoid
                # touching psycopg types when meta is None everywhere.
                from psycopg.types.json import Json  # pylint: disable=import-outside-toplevel
                meta_col = Json(meta) if meta is not None else None
                rows.append((
                    entity_type, entity_id, encoder_id, embed_text,
                    vector_lit, embed_text,  # embed_text also seeds name_lex
                    country, event_date,
                    nuts, sector, meta_col,
                    w[0].seq,
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
                           embedding, name_lex, country, event_date,
                           nuts, sector, meta,
                           last_seq)
                        VALUES
                          (%s, %s, %s, %s,
                           %s::vector, to_tsvector('simple', %s), %s, %s,
                           %s, %s, %s,
                           %s)
                        ON CONFLICT (entity_type, entity_id) DO UPDATE SET
                          encoder_id = EXCLUDED.encoder_id,
                          embed_text = EXCLUDED.embed_text,
                          embedding  = EXCLUDED.embedding,
                          name_lex   = EXCLUDED.name_lex,
                          country    = EXCLUDED.country,
                          event_date = EXCLUDED.event_date,
                          nuts       = EXCLUDED.nuts,
                          sector     = EXCLUDED.sector,
                          meta       = EXCLUDED.meta,
                          last_seq   = EXCLUDED.last_seq,
                          updated_at = now()
                        """,
                        rows,
                    )
        logger.info(
            "batch: %d embedded, %d skipped (last_seq=%s)",
            len(rows), skipped, batch[-1].seq,
        )
