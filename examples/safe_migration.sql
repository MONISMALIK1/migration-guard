-- GOOD migration — safe patterns
-- Run: migration-guard check examples/safe_migration.sql

-- +migrate Up

BEGIN;

ALTER TABLE users ADD COLUMN score INTEGER NOT NULL DEFAULT 0;

CREATE INDEX CONCURRENTLY idx_users_score ON users(score);

COMMIT;

-- +migrate Down

BEGIN;
ALTER TABLE users DROP COLUMN score;
DROP INDEX CONCURRENTLY IF EXISTS idx_users_score;
COMMIT;
