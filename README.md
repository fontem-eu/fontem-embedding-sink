> ### 🪞 This GitHub repository is a mirror
>
> Development happens on Fontem's own infrastructure; this mirror is
> updated automatically. **Issues and pull requests opened here are not
> monitored.**
>
> If you would like to contribute — code, data sources, review, or
> anything else — please get in touch at **team@fontem.eu** and we will
> set you up.

# fontem-embedding-sink

Event consumer that projects `events.entity_events` into a
pgvector-backed embeddings table (`search.entity_embeddings`).

Powers [hybrid search](https://en.wikipedia.org/wiki/Learning_to_rank#Hybrid_ranking):
dense vector similarity (backend-dependent — prod currently runs
`minilm-local`; `labse-local` and `mistral` are also supported) blended with
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
  │  2. linguistics/embed(embed_text)   │─→ dense vector
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
  EMBEDDING_BACKEND     labse-local (default) | minilm-local | mistral
                        (prod runs minilm-local; the whole table must
                        use ONE encoder — see the A/B note below)
  EMBED_BATCH_SIZE      128 (texts per /embed_batch request)
  EMBED_BATCH_CONCURRENCY  4 (parallel /embed_batch chunks in flight)
  EVENT_CONSUMER_NAME   embedding_sink (must match the offset row name)
  EVENT_BATCH_SIZE      100 (recommended — LaBSE ~50ms/call caps throughput)
  METRICS_PORT          9100

## Deploy

CI auto-builds the image on merge to main. The Deployments live
inline in `gitops/infra/prod.yaml` alongside the other sinks
(neo4j-sink / virtuoso-sink pattern). First deploy requires seeding
the initial offset — see `hack/seed-offset.sql`.

NOTE: `search.entity_embeddings`'s PRIMARY KEY is (entity_type,
entity_id) and does NOT include `encoder_id` — two consumers running
different backends clobber each other's rows. All consumers
(embedding_sink, embedding_sink_b) must run the same
EMBEDDING_BACKEND until the PK grows an encoder_id component.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
