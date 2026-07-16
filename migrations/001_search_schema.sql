-- fontem-embedding-sink schema, hosted alongside the events tables in
-- the same Postgres. Kept in its own schema so it can be extracted to
-- a dedicated database later without touching table names or code.

CREATE SCHEMA IF NOT EXISTS search;
CREATE EXTENSION IF NOT EXISTS vector;

-- Vectors are 1024-dim (Mistral-embed). The `encoder_id` is stamped by
-- fontem-linguistics on every /embed response — reject cross-version
-- comparisons at query time (see linguistics/backends/labse_local.py
-- for the versioning convention e.g. "labse@1.0.0-836121a").
CREATE TABLE IF NOT EXISTS search.entity_embeddings (
  entity_type   text        NOT NULL,        -- company | authority | contract | ...
  entity_id     text        NOT NULL,        -- the gmr_id / authority_id / etc.
  encoder_id    text        NOT NULL,        -- e.g. "labse@1.0.0-836121a"
  embed_text    text        NOT NULL,        -- what was actually embedded (audit)
  embedding     vector(1024) NOT NULL,        -- Mistral-embed vector
  name_lex      tsvector    NOT NULL,        -- for hybrid lexical (per-row simple config; per-lang analyzers come later)
  country       text,                        -- pulled from payload when present, for filters
  event_date    date,                        -- publication_date / filed_date / etc., for date filters
  last_seq      bigint      NOT NULL,        -- highest event seq that touched this row (for debugging)
  updated_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (entity_type, entity_id)
);

-- HNSW is the right index for our size — sub-100ms on millions with
-- decent recall, and it doesn't need pre-training like IVFFlat. The
-- default parameters are fine at this scale; tune if we ever have
-- billions of rows (m=16, ef_construction=64 are the defaults).
CREATE INDEX IF NOT EXISTS entity_embeddings_hnsw
  ON search.entity_embeddings
  USING hnsw (embedding vector_cosine_ops);

-- GIN for lexical hybrid.
CREATE INDEX IF NOT EXISTS entity_embeddings_lex
  ON search.entity_embeddings
  USING gin (name_lex);

-- Btrees for the two filters the search UI already exposes.
CREATE INDEX IF NOT EXISTS entity_embeddings_type_country
  ON search.entity_embeddings (entity_type, country);
CREATE INDEX IF NOT EXISTS entity_embeddings_date
  ON search.entity_embeddings (event_date);

COMMENT ON TABLE search.entity_embeddings IS
  'Hybrid search index — one row per (entity_type, entity_id). Populated by fontem-embedding-sink from the events log; query with a cosine-distance lookup on embedding OR a tsvector match on name_lex, then combine via RRF.';
