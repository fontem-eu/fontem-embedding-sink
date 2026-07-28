-- Durable lexical lane for machine translations. TranslateAuthorityName
-- writes ONLY this column; Upsert* events never touch it. The hybrid
-- search matches (name_lex @@ q OR name_lex_i18n @@ q), so translated
-- authority names stay searchable even when an authority is re-loaded
-- (an UpsertAuthority reprojects name_lex/embed_text from its own
-- payload, which carries no translations — that used to clobber them).
-- Nullable: only translated authorities have it.
ALTER TABLE search.entity_embeddings
  ADD COLUMN IF NOT EXISTS name_lex_i18n tsvector;

CREATE INDEX IF NOT EXISTS entity_embeddings_lex_i18n
  ON search.entity_embeddings
  USING gin (name_lex_i18n);

COMMENT ON COLUMN search.entity_embeddings.name_lex_i18n IS
  'Translations-only tsvector (name_<lang> for the 24 EU languages), written by TranslateAuthorityName. Never overwritten by Upsert* events, so translations survive entity re-loads. Query alongside name_lex.';
