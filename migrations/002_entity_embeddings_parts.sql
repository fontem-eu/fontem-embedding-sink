-- The fields each row was composed from, so a later event that states only
-- some of them enriches the row instead of rebuilding it from its own slice.
--
-- Before this, every Upsert* replaced embed_text, the vector, name_lex,
-- country, sector and meta from one payload. A partial producer
-- (load_ted_contracts: a supplier's name and country; load_gleif_relationships:
-- {gmr_id, lei}) therefore cut a GLEIF-described company down to what its own
-- notice said, and search quality with it.
--
-- NULL means "composed before this column existed": the next event for that
-- row merges into an empty base, which is exactly the old behaviour, and from
-- then on the row accumulates. No backfill: embed_text cannot be decomposed
-- back into fields, and a full record event restores it anyway.
ALTER TABLE search.entity_embeddings
  ADD COLUMN IF NOT EXISTS parts jsonb;

COMMENT ON COLUMN search.entity_embeddings.parts IS
  'Merged payload fields this row was composed from (embed_text.PARTS). A stated value wins; an absent or null key keeps the stored one.';
