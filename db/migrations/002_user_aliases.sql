-- Cross-platform identity map for OneRingToRuleThemAll
-- Different platforms (Telegram, Discord) give the same human different user ids.
-- This maps each platform id -> one canonical id so tool lookups (e.g. drophunter
-- games, owned by the Discord id) resolve regardless of which platform sent the message.
-- Run: docker exec -i homelab-postgres psql -U homelab -d homelab < db/migrations/002_user_aliases.sql

CREATE TABLE IF NOT EXISTS master.user_aliases (
    alias_id     TEXT PRIMARY KEY,   -- platform-specific id (e.g. Telegram user id)
    canonical_id TEXT NOT NULL,      -- the unified owner id (the Discord id used by drophunter)
    note         TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed: Telegram user 813187457 -> canonical Discord id 688395953090461801
INSERT INTO master.user_aliases (alias_id, canonical_id, note)
VALUES ('813187457', '688395953090461801', 'Telegram -> Discord (Thomas)')
ON CONFLICT (alias_id) DO UPDATE SET canonical_id = EXCLUDED.canonical_id;

GRANT SELECT ON master.user_aliases TO master_rw;
