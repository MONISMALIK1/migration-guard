-- BAD migration — multiple critical issues
-- Run: migration-guard check examples/risky_migration.sql

ALTER TABLE users ADD COLUMN score INTEGER NOT NULL;

DROP TABLE legacy_sessions;

ALTER TABLE orders RENAME COLUMN total TO order_total;

CREATE INDEX idx_users_email ON users(email);

ALTER TABLE payments ADD CONSTRAINT chk_positive CHECK (amount > 0);
