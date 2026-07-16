-- Hybrid search: dense (vector) + sparse (tsvector), merged with RRF.
--
-- Params (psycopg named):
--   %(q)s       query text (drives the tsvector match)
--   %(qvec)s    query embedding as vector literal '[...]'
--   %(enc)s     encoder_id (must match corpus so we compare like-with-like)
--   %(country)s country filter, nullable
--   %(types)s   entity_type filter, nullable text[]
--   %(limit)s   final result count
--
-- Two CTEs, one FULL OUTER JOIN, RRF ORDER BY. Constant 60 is the
-- standard RRF dampener; weights are 1.0/1.0 for now (tune to 0.7/1.0
-- if lexical over-dominates once real users hit this).
WITH lex AS (
  SELECT entity_type, entity_id, embed_text, country, event_date,
         ROW_NUMBER() OVER (ORDER BY ts_rank(name_lex, plainto_tsquery('simple', %(q)s)) DESC) AS rk
  FROM search.entity_embeddings
  WHERE name_lex @@ plainto_tsquery('simple', %(q)s)
    AND (%(country)s::text IS NULL OR country = %(country)s)
    AND (%(types)s::text[] IS NULL OR entity_type = ANY(%(types)s))
  ORDER BY rk
  LIMIT 100
),
vec AS (
  SELECT entity_type, entity_id, embed_text, country, event_date,
         ROW_NUMBER() OVER (ORDER BY embedding <=> %(qvec)s::vector) AS rk
  FROM search.entity_embeddings
  WHERE encoder_id = %(enc)s
    AND (%(country)s::text IS NULL OR country = %(country)s)
    AND (%(types)s::text[] IS NULL OR entity_type = ANY(%(types)s))
  ORDER BY embedding <=> %(qvec)s::vector
  LIMIT 100
)
SELECT
  COALESCE(l.entity_type, v.entity_type) AS entity_type,
  COALESCE(l.entity_id, v.entity_id)     AS entity_id,
  COALESCE(l.embed_text, v.embed_text)   AS embed_text,
  COALESCE(l.country, v.country)         AS country,
  COALESCE(l.event_date, v.event_date)   AS event_date,
  l.rk                                    AS lex_rank,
  v.rk                                    AS vec_rank,
  ROUND((
    (CASE WHEN l.rk IS NULL THEN 0 ELSE 1.0 / (60 + l.rk) END) +
    (CASE WHEN v.rk IS NULL THEN 0 ELSE 1.0 / (60 + v.rk) END)
  )::numeric, 5) AS rrf_score
FROM lex l
FULL OUTER JOIN vec v USING (entity_type, entity_id)
ORDER BY rrf_score DESC
LIMIT %(limit)s;
