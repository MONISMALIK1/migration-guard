"""Tests for all risk rules."""

import pytest
from migration_guard.parser import ParsedMigration, MigrationFormat
from migration_guard.rules import (
    Severity, run_rules,
    check_not_null_without_default, check_drop_table, check_truncate,
    check_no_rollback, check_drop_column, check_rename_table, check_rename_column,
    check_missing_fk_index, check_no_transaction, check_index_without_concurrently,
    check_column_type_change, check_constraint_without_not_valid,
)


def make_migration(up_sql="", down_sql="", has_rollback=None, has_transaction=True,
                   raw=None, fmt=MigrationFormat.SQL):
    if has_rollback is None:
        has_rollback = bool(down_sql.strip())
    if raw is None:
        raw = up_sql
    from migration_guard.parser import _split_statements
    return ParsedMigration(
        path="test.sql",
        format=fmt,
        raw=raw,
        up_sql=up_sql,
        down_sql=down_sql,
        statements=_split_statements(up_sql),
        has_rollback=has_rollback,
        has_transaction=has_transaction,
        filename="test.sql",
    )


# ── NOT NULL without DEFAULT ─────────────────────────────────────────────────

class TestNotNullNoDefault:
    def test_flags_not_null_without_default(self):
        m = make_migration("ALTER TABLE users ADD COLUMN age INTEGER NOT NULL;")
        v = check_not_null_without_default(m)
        assert len(v) == 1
        assert v[0].severity == Severity.CRITICAL
        assert v[0].rule_id == "NOT_NULL_NO_DEFAULT"

    def test_passes_when_default_present(self):
        m = make_migration("ALTER TABLE users ADD COLUMN age INTEGER NOT NULL DEFAULT 0;")
        assert check_not_null_without_default(m) == []

    def test_passes_nullable_column(self):
        m = make_migration("ALTER TABLE users ADD COLUMN age INTEGER;")
        assert check_not_null_without_default(m) == []

    def test_passes_clean_migration(self):
        m = make_migration("CREATE TABLE foo (id SERIAL PRIMARY KEY);")
        assert check_not_null_without_default(m) == []


# ── DROP TABLE ───────────────────────────────────────────────────────────────

class TestDropTable:
    def test_flags_drop_table(self):
        m = make_migration("DROP TABLE users;")
        v = check_drop_table(m)
        assert len(v) == 1
        assert v[0].severity == Severity.CRITICAL
        assert v[0].rule_id == "DROP_TABLE"

    def test_flags_drop_table_if_exists(self):
        m = make_migration("DROP TABLE IF EXISTS legacy_data;")
        v = check_drop_table(m)
        assert len(v) == 1

    def test_no_flag_on_create(self):
        m = make_migration("CREATE TABLE users (id SERIAL);")
        assert check_drop_table(m) == []


# ── TRUNCATE ─────────────────────────────────────────────────────────────────

class TestTruncate:
    def test_flags_truncate(self):
        m = make_migration("TRUNCATE TABLE sessions;")
        v = check_truncate(m)
        assert len(v) == 1
        assert v[0].severity == Severity.CRITICAL
        assert v[0].rule_id == "TRUNCATE"

    def test_no_flag_on_delete(self):
        m = make_migration("DELETE FROM sessions WHERE expired = true;")
        assert check_truncate(m) == []


# ── NO ROLLBACK ──────────────────────────────────────────────────────────────

class TestNoRollback:
    def test_flags_missing_rollback(self):
        m = make_migration("CREATE TABLE foo (id SERIAL);", has_rollback=False)
        v = check_no_rollback(m)
        assert len(v) == 1
        assert v[0].severity == Severity.CRITICAL
        assert v[0].rule_id == "NO_ROLLBACK"

    def test_passes_with_rollback(self):
        m = make_migration("CREATE TABLE foo (id SERIAL);", down_sql="DROP TABLE foo;")
        assert check_no_rollback(m) == []


# ── DROP COLUMN ──────────────────────────────────────────────────────────────

class TestDropColumn:
    def test_flags_drop_column(self):
        m = make_migration("ALTER TABLE users DROP COLUMN legacy_name;")
        v = check_drop_column(m)
        assert len(v) == 1
        assert v[0].severity == Severity.HIGH
        assert v[0].rule_id == "DROP_COLUMN"
        assert "legacy_name" in v[0].message

    def test_flags_multiple_drops(self):
        sql = """
        ALTER TABLE users DROP COLUMN col1;
        ALTER TABLE orders DROP COLUMN col2;
        """
        m = make_migration(sql)
        v = check_drop_column(m)
        assert len(v) == 2

    def test_no_flag_on_add(self):
        m = make_migration("ALTER TABLE users ADD COLUMN new_col TEXT;")
        assert check_drop_column(m) == []


# ── RENAME TABLE ─────────────────────────────────────────────────────────────

class TestRenameTable:
    def test_flags_rename_table(self):
        m = make_migration("RENAME TABLE users TO accounts;")
        v = check_rename_table(m)
        assert len(v) == 1
        assert v[0].severity == Severity.HIGH

    def test_flags_alter_rename_to(self):
        m = make_migration("ALTER TABLE users RENAME TO accounts;")
        v = check_rename_table(m)
        assert len(v) == 1

    def test_no_flag_on_create(self):
        m = make_migration("CREATE TABLE users (id SERIAL);")
        assert check_rename_table(m) == []


# ── RENAME COLUMN ────────────────────────────────────────────────────────────

class TestRenameColumn:
    def test_flags_rename_column(self):
        m = make_migration("ALTER TABLE users RENAME COLUMN old_name TO new_name;")
        v = check_rename_column(m)
        assert len(v) == 1
        assert v[0].severity == Severity.HIGH
        assert v[0].rule_id == "RENAME_COLUMN"

    def test_no_flag_on_add(self):
        m = make_migration("ALTER TABLE users ADD COLUMN new_col TEXT;")
        assert check_rename_column(m) == []


# ── MISSING FK INDEX ─────────────────────────────────────────────────────────

class TestMissingFKIndex:
    def test_flags_fk_without_index(self):
        sql = "ALTER TABLE orders ADD COLUMN user_id INTEGER REFERENCES users(id);"
        m = make_migration(sql)
        v = check_missing_fk_index(m)
        assert len(v) == 1
        assert v[0].severity == Severity.MEDIUM
        assert v[0].rule_id == "MISSING_FK_INDEX"

    def test_passes_fk_with_index(self):
        sql = """
        ALTER TABLE orders ADD COLUMN user_id INTEGER REFERENCES users(id);
        CREATE INDEX ON orders(user_id);
        """
        m = make_migration(sql)
        v = check_missing_fk_index(m)
        assert v == []

    def test_flags_foreign_key_constraint(self):
        sql = "ALTER TABLE orders ADD CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id);"
        m = make_migration(sql)
        v = check_missing_fk_index(m)
        assert len(v) == 1


# ── NO TRANSACTION ───────────────────────────────────────────────────────────

class TestNoTransaction:
    def test_flags_multi_statement_without_txn(self):
        sql = "CREATE TABLE a (id INT); CREATE TABLE b (id INT);"
        m = make_migration(sql, has_transaction=False, fmt=MigrationFormat.SQL)
        v = check_no_transaction(m)
        assert len(v) == 1
        assert v[0].severity == Severity.MEDIUM

    def test_passes_single_statement(self):
        sql = "CREATE TABLE a (id INT);"
        m = make_migration(sql, has_transaction=False)
        v = check_no_transaction(m)
        assert v == []

    def test_passes_with_transaction(self):
        sql = "BEGIN; CREATE TABLE a (id INT); CREATE TABLE b (id INT); COMMIT;"
        m = make_migration(sql, has_transaction=True)
        v = check_no_transaction(m)
        assert v == []

    def test_django_skips_transaction_check(self):
        sql = "ALTER TABLE a DROP COLUMN x; ALTER TABLE b DROP COLUMN y;"
        m = make_migration(sql, has_transaction=False, fmt=MigrationFormat.DJANGO)
        v = check_no_transaction(m)
        assert v == []


# ── INDEX WITHOUT CONCURRENTLY ───────────────────────────────────────────────

class TestIndexWithoutConcurrently:
    def test_flags_index_without_concurrently(self):
        m = make_migration("CREATE INDEX idx_users_email ON users(email);")
        v = check_index_without_concurrently(m)
        assert len(v) == 1
        assert v[0].severity == Severity.LOW
        assert v[0].rule_id == "INDEX_WITHOUT_CONCURRENTLY"

    def test_passes_concurrent_index(self):
        m = make_migration("CREATE INDEX CONCURRENTLY idx_users_email ON users(email);")
        assert check_index_without_concurrently(m) == []

    def test_no_flag_on_create_table(self):
        m = make_migration("CREATE TABLE users (id SERIAL);")
        assert check_index_without_concurrently(m) == []


# ── COLUMN TYPE CHANGE ───────────────────────────────────────────────────────

class TestColumnTypeChange:
    def test_flags_alter_column_type(self):
        m = make_migration("ALTER TABLE users ALTER COLUMN age TYPE BIGINT;")
        v = check_column_type_change(m)
        assert len(v) == 1
        assert v[0].severity == Severity.HIGH

    def test_flags_set_data_type(self):
        m = make_migration("ALTER TABLE users ALTER COLUMN score SET DATA TYPE NUMERIC(10,2);")
        v = check_column_type_change(m)
        assert len(v) == 1

    def test_no_flag_on_add_column(self):
        m = make_migration("ALTER TABLE users ADD COLUMN score NUMERIC;")
        assert check_column_type_change(m) == []


# ── CONSTRAINT WITHOUT NOT VALID ─────────────────────────────────────────────

class TestConstraintWithoutNotValid:
    def test_flags_check_constraint(self):
        m = make_migration("ALTER TABLE orders ADD CONSTRAINT chk_amount CHECK (amount > 0);")
        v = check_constraint_without_not_valid(m)
        assert len(v) == 1
        assert v[0].severity == Severity.MEDIUM

    def test_passes_with_not_valid(self):
        m = make_migration(
            "ALTER TABLE orders ADD CONSTRAINT chk_amount CHECK (amount > 0) NOT VALID;"
        )
        assert check_constraint_without_not_valid(m) == []


# ── run_rules integration ────────────────────────────────────────────────────

class TestRunRules:
    def test_run_all_rules_clean(self):
        m = make_migration(
            "CREATE TABLE foo (id SERIAL PRIMARY KEY, name TEXT);",
            has_rollback=True,
            has_transaction=True,
        )
        v = run_rules(m)
        assert v == []

    def test_skip_rule(self):
        m = make_migration("DROP TABLE users;", has_rollback=False)
        all_v = run_rules(m)
        skipped_v = run_rules(m, skip_rules=["DROP_TABLE", "NO_ROLLBACK"])
        assert len(skipped_v) < len(all_v)
        assert all(v.rule_id not in ("DROP_TABLE", "NO_ROLLBACK") for v in skipped_v)

    def test_min_severity_filter(self):
        m = make_migration("CREATE INDEX idx ON users(email);", has_rollback=True)
        low_v = run_rules(m, min_severity=Severity.LOW)
        high_v = run_rules(m, min_severity=Severity.HIGH)
        assert len(low_v) >= len(high_v)

    def test_multiple_violations(self):
        sql = """
        DROP TABLE legacy;
        ALTER TABLE users ADD COLUMN score INT NOT NULL;
        ALTER TABLE orders RENAME COLUMN old_col TO new_col;
        """
        m = make_migration(sql, has_rollback=False)
        v = run_rules(m)
        rule_ids = {viol.rule_id for viol in v}
        assert "DROP_TABLE" in rule_ids
        assert "NOT_NULL_NO_DEFAULT" in rule_ids
        assert "RENAME_COLUMN" in rule_ids
        assert "NO_ROLLBACK" in rule_ids
