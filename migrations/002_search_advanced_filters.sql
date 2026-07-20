-- Adds first-class filter columns for the advanced-search panel
-- (nuts region prefix, sector top code) plus a jsonb `meta` bucket
-- for the long tail of per-type fields the UI/API may want to
-- filter or display in the future.
--
-- Additive only. Backfill via a full sink re-run over the event log.

ALTER TABLE search.entity_embeddings
  ADD COLUMN IF NOT EXISTS nuts   text,
  ADD COLUMN IF NOT EXISTS sector text,
  ADD COLUMN IF NOT EXISTS meta   jsonb;

-- text_pattern_ops so prefix LIKE 'PT18%' can use the btree.
-- Regular btree wouldn't help for LIKE — the pattern-ops variant is
-- what makes region-cascade filters cheap.
CREATE INDEX IF NOT EXISTS entity_embeddings_nuts
  ON search.entity_embeddings (nuts text_pattern_ops)
  WHERE nuts IS NOT NULL;

CREATE INDEX IF NOT EXISTS entity_embeddings_sector
  ON search.entity_embeddings (sector)
  WHERE sector IS NOT NULL;

-- jsonb_path_ops is smaller and faster than jsonb_ops for the
-- containment operator we intend to use (@>), which is the whole
-- point of the meta column.
CREATE INDEX IF NOT EXISTS entity_embeddings_meta
  ON search.entity_embeddings USING gin (meta jsonb_path_ops)
  WHERE meta IS NOT NULL;
