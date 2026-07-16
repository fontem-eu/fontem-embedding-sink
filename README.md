# fontem-embedding-sink

Event consumer that projects `events.entity_events` into a
pgvector-backed embeddings table (`search.entity_embeddings`).

Powers [hybrid search](https://en.wikipedia.org/wiki/Learning_to_rank#Hybrid_ranking):
dense vector similarity (LaBSE, 768-dim, multilingual) blended with
Postgres `tsvector` lexical match via reciprocal rank fusion.
Query time is a single SQL statement, results are already mixed
across entity types (no per-type federator, no "results by group"
sidebars — one relevance-ranked list).

## Architecture

  events.entity_events           search.entity_embeddings
  ─────────────                  ─────────────
        │                             ▲
        │  batch of Upsert*           │
        ▼                             │
  ┌──────────────────────────────────────┐
  │        fontem-embedding-sink        │
  │  1. COMPOSERS[event_type](payload)  │─→ skip if no composer
  │  2. linguistics/embed(embed_text)   │─→ LaBSE 768-d
  │  3. UPSERT into search table        │
  └──────────────────────────────────────┘

The sink is idempotent — the pk `(entity_type, entity_id)` means a
replay overwrites cleanly. Following the fontem-events contract
the offset row lives in `events.consumer_offsets` under the name
`embedding_sink`; the offset advance and the row UPSERT commit in
the same transaction.

## Env

  EVENTS_DATABASE_URL   the events postgres (both events + search tables)
  SEARCH_DATABASE_URL   optional; defaults to EVENTS_DATABASE_URL
  LINGUISTICS_URL       http://fontem-linguistics.linguistics-service.svc:8080
  EMBEDDING_BACKEND     labse_local (default) | mistral
  EVENT_CONSUMER_NAME   embedding_sink (must match the offset row name)
  EVENT_BATCH_SIZE      100 (recommended — LaBSE ~50ms/call caps throughput)
  METRICS_PORT          9100

## Deploy

CI auto-builds the image on merge to main; deploy via gitops/shared/
`fontem-embedding-sink.yaml` alongside the other sinks. First deploy
requires seeding the initial offset — see `hack/seed-offset.sql`.
