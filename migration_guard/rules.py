"""Risk rules engine — checks migration content for dangerous patterns."""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from .parser import ParsedMigration


class Severity(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    def __str__(self):
        return self.name

    def __ge__(self, other):
        return self.value >= other.value

    def __gt__(self, other):
        return self.value > other.value

    def __le__(self, other):
        return self.value <= other.value

    def __lt__(self, other):
        return self.value < other.value


@dataclass
class RuleViolation:
    rule_id: str
    severity: Severity
    message: str
    detail: str
    suggestion: str
    line: Optional[int] = None

    def __str__(self):
        return f"[{self.severity}] {self.message}"


# ── Individual rules ─────────────────────────────────────────────────────────

def _find_line(content: str, pattern: str) -> Optional[int]:
    """Find 1-based line number of first regex match."""
    for i, line in enumerate(content.splitlines(), 1):
        if re.search(pattern, line, re.IGNORECASE):
            return i
    return None


def check_not_null_without_default(migration: ParsedMigration) -> list[RuleViolation]:
    """ADD COLUMN NOT NULL without DEFAULT will lock the table during backfill."""
    violations = []
    # Split into individual statements and check each one
    for stmt in migration.statements:
        stmt_upper = stmt.upper()
        if "ADD COLUMN" not in stmt_upper and "ADD  COLUMN" not in stmt_upper:
            continue
        if "NOT NULL" not in stmt_upper:
            continue
        if "DEFAULT" in stmt_upper:
            continue  # DEFAULT present anywhere in this statement — safe
        line = _find_line(migration.raw, r"ADD\s+COLUMN.*NOT\s+NULL")
        violations.append(RuleViolation(
            rule_id="NOT_NULL_NO_DEFAULT",
            severity=Severity.CRITICAL,
            message="NOT NULL column added without DEFAULT",
            detail=(
                "Adding a NOT NULL column without a DEFAULT will lock the entire table "
                "while the database backfills existing rows. On large tables this can "
                "take hours and block all reads and writes."
            ),
            suggestion=(
                "Add a DEFAULT value, or use a 3-step approach: "
                "(1) add column nullable, (2) backfill, (3) add NOT NULL constraint."
            ),
            line=line,
        ))
    return violations


def check_drop_table(migration: ParsedMigration) -> list[RuleViolation]:
    """DROP TABLE is irreversible without a backup."""
    violations = []
    for m in re.finditer(r"\bDROP\s+TABLE\b", migration.up_sql, re.IGNORECASE):
        line = _find_line(migration.raw, r"DROP\s+TABLE")
        violations.append(RuleViolation(
            rule_id="DROP_TABLE",
            severity=Severity.CRITICAL,
            message="DROP TABLE detected",
            detail=(
                "Dropping a table is irreversible. If the deployment fails after this "
                "migration runs, you cannot roll back without a full database restore."
            ),
            suggestion=(
                "Rename the table first (`ALTER TABLE x RENAME TO x_deprecated_YYYYMMDD`), "
                "keep it for one release cycle, then drop it in a follow-up migration."
            ),
            line=line,
        ))
    return violations


def check_truncate(migration: ParsedMigration) -> list[RuleViolation]:
    """TRUNCATE deletes all data immediately."""
    violations = []
    for m in re.finditer(r"\bTRUNCATE\b", migration.up_sql, re.IGNORECASE):
        line = _find_line(migration.raw, r"\bTRUNCATE\b")
        violations.append(RuleViolation(
            rule_id="TRUNCATE",
            severity=Severity.CRITICAL,
            message="TRUNCATE detected",
            detail="TRUNCATE immediately deletes all rows and cannot be easily undone.",
            suggestion="Use DELETE with a WHERE clause instead, or ensure data is backed up first.",
            line=line,
        ))
    return violations


def check_no_rollback(migration: ParsedMigration) -> list[RuleViolation]:
    """Migration has no rollback / down section."""
    if migration.has_rollback:
        return []
    return [RuleViolation(
        rule_id="NO_ROLLBACK",
        severity=Severity.CRITICAL,
        message="No rollback / DOWN migration found",
        detail=(
            "If this migration causes issues in production, there is no automated way "
            "to revert it. A bad deploy could require manual DB intervention."
        ),
        suggestion=(
            "Add a -- Down section (SQL), downgrade() function (Alembic), "
            "or ensure all operations are reversible by Django's migration framework."
        ),
    )]


def check_drop_column(migration: ParsedMigration) -> list[RuleViolation]:
    """DROP COLUMN may break code that still references it."""
    violations = []
    for m in re.finditer(
        r"\bDROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?(\w+)", migration.up_sql, re.IGNORECASE
    ):
        col_name = m.group(1)
        line = _find_line(migration.raw, r"DROP\s+COLUMN")
        violations.append(RuleViolation(
            rule_id="DROP_COLUMN",
            severity=Severity.HIGH,
            message=f"DROP COLUMN '{col_name}' detected",
            detail=(
                f"Dropping column '{col_name}' will fail if any running code (ORM models, "
                f"raw queries, stored procedures) still references it."
            ),
            suggestion=(
                "Deploy code that stops using the column first, verify in production, "
                "then drop it in a separate migration."
            ),
            line=line,
        ))
    return violations


def check_rename_table(migration: ParsedMigration) -> list[RuleViolation]:
    """Renaming a table instantly breaks all queries that reference the old name."""
    violations = []
    patterns = [
        r"\bRENAME\s+TABLE\b",
        r"\bALTER\s+TABLE\s+\w+\s+RENAME\s+TO\b",
    ]
    for pat in patterns:
        for m in re.finditer(pat, migration.up_sql, re.IGNORECASE):
            line = _find_line(migration.raw, pat)
            violations.append(RuleViolation(
                rule_id="RENAME_TABLE",
                severity=Severity.HIGH,
                message="RENAME TABLE detected",
                detail=(
                    "Renaming a table instantly breaks all existing queries, ORM mappings, "
                    "and views that reference the old table name."
                ),
                suggestion=(
                    "Use a view with the old name pointing to the new table, "
                    "or do a blue/green deploy with both names supported."
                ),
                line=line,
            ))
    return violations


def check_rename_column(migration: ParsedMigration) -> list[RuleViolation]:
    """Renaming a column breaks all queries that reference the old column name."""
    violations = []
    # Single pattern — avoids double-counting overlapping matches
    for m in re.finditer(r"\bRENAME\s+COLUMN\b", migration.up_sql, re.IGNORECASE):
        line = _find_line(migration.raw, r"\bRENAME\s+COLUMN\b")
        violations.append(RuleViolation(
            rule_id="RENAME_COLUMN",
            severity=Severity.HIGH,
            message="RENAME COLUMN detected",
            detail=(
                "Renaming a column breaks all queries, ORM field mappings, "
                "and any raw SQL referencing the old column name."
            ),
            suggestion=(
                "Add a new column, copy data, update code to use new column, "
                "then drop the old column in a separate migration."
            ),
            line=line,
        ))
    return violations


def check_missing_fk_index(migration: ParsedMigration) -> list[RuleViolation]:
    """Foreign key column added without a corresponding index."""
    violations = []
    sql_upper = migration.up_sql.upper()

    # Find FK references
    fk_cols = set()
    # ADD COLUMN col_name TYPE REFERENCES ... (skip ADD CONSTRAINT)
    for m in re.finditer(
        r"ADD\s+COLUMN\s+(\w+)\s+\w+.*?REFERENCES\s+\w+",
        migration.up_sql, re.IGNORECASE | re.DOTALL
    ):
        fk_cols.add(m.group(1).upper())

    for m in re.finditer(
        r"FOREIGN\s+KEY\s*\((\w+)\)", migration.up_sql, re.IGNORECASE
    ):
        fk_cols.add(m.group(1).upper())

    # Check Django/Alembic FK comment hints
    for m in re.finditer(r"-- FK: \S+\.(\w+) needs index", migration.up_sql):
        fk_cols.add(m.group(1).upper())

    for col in fk_cols:
        # Check if there's a CREATE INDEX on this column
        if not re.search(
            rf"CREATE\s+(?:UNIQUE\s+)?INDEX.*\b{col}\b", sql_upper
        ):
            violations.append(RuleViolation(
                rule_id="MISSING_FK_INDEX",
                severity=Severity.MEDIUM,
                message=f"Foreign key column '{col.lower()}' has no index",
                detail=(
                    f"Column '{col.lower()}' is a foreign key but has no index. "
                    "Every JOIN or lookup on this column will do a full table scan."
                ),
                suggestion=f"Add: CREATE INDEX ON <table>({col.lower()});",
            ))
    return violations


def check_no_transaction(migration: ParsedMigration) -> list[RuleViolation]:
    """Multi-statement migration not wrapped in a transaction."""
    if migration.has_transaction:
        return []
    if len(migration.statements) < 2:
        return []
    # Django and Alembic handle transactions themselves
    from .parser import MigrationFormat
    if migration.format in (MigrationFormat.DJANGO, MigrationFormat.ALEMBIC):
        return []

    return [RuleViolation(
        rule_id="NO_TRANSACTION",
        severity=Severity.MEDIUM,
        message="Multiple statements without transaction wrapping",
        detail=(
            f"This migration has {len(migration.statements)} statements but is not wrapped "
            "in BEGIN/COMMIT. If any statement fails, earlier statements will not be rolled back, "
            "leaving the database in a partial state."
        ),
        suggestion="Wrap all statements in BEGIN; ... COMMIT; or use a savepoint strategy.",
    )]


def check_index_without_concurrently(migration: ParsedMigration) -> list[RuleViolation]:
    """CREATE INDEX without CONCURRENTLY locks the table during index build."""
    violations = []
    for m in re.finditer(r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\b", migration.up_sql, re.IGNORECASE):
        snippet = migration.up_sql[m.start():m.start() + 200]
        if "CONCURRENTLY" not in snippet.upper():
            line = _find_line(migration.raw, r"CREATE\s+(?:UNIQUE\s+)?INDEX")
            violations.append(RuleViolation(
                rule_id="INDEX_WITHOUT_CONCURRENTLY",
                severity=Severity.LOW,
                message="CREATE INDEX without CONCURRENTLY",
                detail=(
                    "Creating an index without CONCURRENTLY locks the table for writes "
                    "until the index build is complete. On large tables this can cause downtime."
                ),
                suggestion="Use CREATE INDEX CONCURRENTLY to build the index without locking.",
                line=line,
            ))
    return violations


def check_column_type_change(migration: ParsedMigration) -> list[RuleViolation]:
    """Changing a column's data type can cause implicit table rewrites."""
    violations = []
    patterns = [
        r"ALTER\s+COLUMN\s+\w+\s+(?:SET\s+DATA\s+)?TYPE\b",  # PostgreSQL
        r"MODIFY\s+COLUMN\s+\w+\s+\w+",                       # MySQL
    ]
    seen = set()
    for pat in patterns:
        for m in re.finditer(pat, migration.up_sql, re.IGNORECASE):
            if m.start() in seen:
                continue
            seen.add(m.start())
            line = _find_line(migration.raw, pat)
            violations.append(RuleViolation(
                rule_id="COLUMN_TYPE_CHANGE",
                severity=Severity.HIGH,
                message="Column type change detected",
                detail=(
                    "Changing a column's data type may require a full table rewrite, "
                    "which locks the table and can take a long time on large tables. "
                    "It may also cause data truncation or conversion errors."
                ),
                suggestion=(
                    "Add a new column with the desired type, migrate data, "
                    "update code, then drop the old column."
                ),
                line=line,
            ))
    return violations


def check_constraint_without_not_valid(migration: ParsedMigration) -> list[RuleViolation]:
    """Adding a CHECK or FK constraint validates all existing rows (table lock)."""
    violations = []
    for m in re.finditer(
        r"ADD\s+CONSTRAINT\s+\w+\s+(?:CHECK|FOREIGN\s+KEY)\b",
        migration.up_sql, re.IGNORECASE
    ):
        snippet = migration.up_sql[m.start():m.start() + 200]
        if "NOT VALID" not in snippet.upper():
            line = _find_line(migration.raw, r"ADD\s+CONSTRAINT")
            violations.append(RuleViolation(
                rule_id="CONSTRAINT_WITHOUT_NOT_VALID",
                severity=Severity.MEDIUM,
                message="Constraint added without NOT VALID",
                detail=(
                    "Adding a CHECK or FOREIGN KEY constraint without NOT VALID "
                    "will validate all existing rows immediately, locking the table."
                ),
                suggestion=(
                    "Use ADD CONSTRAINT ... NOT VALID to skip existing row validation, "
                    "then VALIDATE CONSTRAINT in a separate step during low-traffic hours."
                ),
                line=line,
            ))
    return violations


# ── Rule registry ─────────────────────────────────────────────────────────────

ALL_RULES = [
    check_not_null_without_default,
    check_drop_table,
    check_truncate,
    check_no_rollback,
    check_drop_column,
    check_rename_table,
    check_rename_column,
    check_missing_fk_index,
    check_no_transaction,
    check_index_without_concurrently,
    check_column_type_change,
    check_constraint_without_not_valid,
]


def run_rules(
    migration: ParsedMigration,
    skip_rules: list[str] = None,
    min_severity: Severity = Severity.LOW,
) -> list[RuleViolation]:
    """Run all rules against a parsed migration and return violations."""
    skip_rules = skip_rules or []
    violations = []
    for rule_fn in ALL_RULES:
        try:
            results = rule_fn(migration)
            for v in results:
                if v.rule_id not in skip_rules and v.severity >= min_severity:
                    violations.append(v)
        except Exception:
            pass  # don't let a broken rule crash the whole run
    return violations
