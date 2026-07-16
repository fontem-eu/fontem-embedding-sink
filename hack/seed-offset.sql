-- Seed the initial offset for the embedding_sink consumer.
-- Sets it to MAX(seq) - 100_000 so the first backfill run
-- covers only the tail 100k events (measurement pass), per the
-- 2026-07-15 experiment plan.
--
-- Re-running this REWINDS. Only intended for the initial seed.
INSERT INTO events.consumer_offsets (consumer_name, last_seq, updated_at)
SELECT 'embedding_sink', GREATEST(MAX(seq) - 100000, 0), now()
FROM events.entity_events
ON CONFLICT (consumer_name) DO NOTHING;
