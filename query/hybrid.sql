-- Hybrid search: dense (vector) + sparse (tsvector), merged with RRF.
--
-- $1 = query text (used for the tsvector match)
-- $2 = query embedding (1024-dim vector literal, from linguistics /embed)
-- $3 = encoder_id (must match the corpus so we compare like-with-like)
-- $4 = country filter, nullable
-- $5 = entity_type filter, nullable text[]
-- $6 = limit
--
-- Each CTE runs its own ranking on its own index (HNSW for dense,
-- GIN for sparse). The FULL OUTER JOIN unions the two candidate sets;
-- rows that only rank in one method still score, but weaker.
--
-- RRF constant = 60 (standard).  Weights = 1.0 each; tune if lexical
-- turns out to under/overweight in practice (0.7 lex / 1.0 vec is a
-- common tweak once real users are involved).
WITH lex AS (
  SELECT entity_type, entity_id, embed_text, country, event_date,
         ROW_NUMBER() OVER (ORDER BY ts_rank(name_lex, plainto_tsquery('simple', $1)) DESC) AS rk
  FROM search.entity_embeddings
  WHERE name_lex @@ plainto_tsquery('simple', $1)
    AND ($4::text IS NULL OR country = $4)
    AND ($5::text[] IS NULL OR entity_type = ANY($5))
  ORDER BY rk
  LIMIT 100
),
vec AS (
  SELECT entity_type, entity_id, embed_text, country, event_date,
         ROW_NUMBER() OVER (ORDER BY embedding <=> $2::vector) AS rk
  FROM search.entity_embeddings
  WHERE encoder_id = $3
    AND ($4::text IS NULL OR country = $4)
    AND ($5::text[] IS NULL OR entity_type = ANY($5))
  ORDER BY embedding <=> $2::vector
  LIMIT 100
)
SELECT
  COALESCE(l.entity_type, v.entity_type) AS entity_type,
  COALESCE(l.entity_id, v.entity_id) AS entity_id,
  COALESCE(l.embed_text, v.embed_text) AS embed_text,
  COALESCE(l.country, v.country) AS country,
  COALESCE(l.event_date, v.event_date) AS event_date,
  l.rk AS lex_rank,
  v.rk AS vec_rank,
  ROUND((
    (CASE WHEN l.rk IS NULL THEN 0 ELSE 1.0 / (60 + l.rk) END) +
    (CASE WHEN v.rk IS NULL THEN 0 ELSE 1.0 / (60 + v.rk) END)
  )::numeric, 5) AS rrf_score
FROM lex l
FULL OUTER JOIN vec v USING (entity_type, entity_id)
ORDER BY rrf_score DESC
LIMIT $6;
