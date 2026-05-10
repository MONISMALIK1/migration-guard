"""Migration file parser — supports SQL, Django, and Alembic formats."""

import re
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MigrationFormat(Enum):
    SQL = "sql"
    DJANGO = "django"
    ALEMBIC = "alembic"
    UNKNOWN = "unknown"


@dataclass
class ParsedMigration:
    path: str
    format: MigrationFormat
    raw: str                        # full file content
    up_sql: str                     # DDL statements (up/forward migration)
    down_sql: str                   # rollback statements (down/reverse migration)
    statements: list[str]           # individual SQL statements from up_sql
    has_rollback: bool              # whether a down/rollback section exists
    has_transaction: bool           # wrapped in BEGIN/COMMIT
    filename: str = ""


# ── SQL helpers ──────────────────────────────────────────────────────────────

def _strip_comments(sql: str) -> str:
    """Remove -- line comments and /* block */ comments."""
    sql = re.sub(r"--[^\n]*", "", sql)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return sql


def _split_statements(sql: str) -> list[str]:
    """Split SQL text into individual statements on semicolons."""
    stmts = []
    for s in sql.split(";"):
        s = s.strip()
        if s:
            stmts.append(s)
    return stmts


def _has_transaction(sql: str) -> bool:
    upper = sql.upper()
    return ("BEGIN" in upper or "START TRANSACTION" in upper) and (
        "COMMIT" in upper or "ROLLBACK" in upper
    )


# ── SQL parser ───────────────────────────────────────────────────────────────

def _parse_sql(path: str, content: str) -> ParsedMigration:
    filename = os.path.basename(path).lower()
    stripped = _strip_comments(content)

    # Detect up/down sections by common comment markers
    up_sql = stripped
    down_sql = ""

    # Patterns: "-- +migrate Down", "-- Down", "-- !Downs", "-- rollback"
    down_patterns = [
        r"--\s*\+migrate\s+Down",
        r"--\s*Down\b",
        r"--\s*rollback\b",
        r"--\s*!Down",
        r"--\s*Revert",
    ]
    raw_stripped = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    for pat in down_patterns:
        m = re.search(pat, raw_stripped, re.IGNORECASE)
        if m:
            up_sql = _strip_comments(raw_stripped[:m.start()])
            down_sql = _strip_comments(raw_stripped[m.end():])
            break

    has_rollback = bool(down_sql.strip())

    # If no inline down, check for a paired _down.sql / .rollback.sql file
    if not has_rollback:
        base = re.sub(r"\.sql$", "", path, flags=re.IGNORECASE)
        candidates = [base + "_down.sql", base + ".rollback.sql"]
        # Only add replace-based candidates when the filename actually ends with up.sql
        fname = os.path.basename(path).lower()
        if fname.endswith("up.sql"):
            candidates.append(path[:-6] + "down.sql")
        if fname.endswith("_up.sql"):
            candidates.append(path[:-7] + "_down.sql")
        for c in candidates:
            if c != path and os.path.exists(c):
                has_rollback = True
                with open(c) as f:
                    down_sql = f.read()
                break

    statements = _split_statements(up_sql)
    has_txn = _has_transaction(content)

    return ParsedMigration(
        path=path,
        format=MigrationFormat.SQL,
        raw=content,
        up_sql=up_sql,
        down_sql=down_sql,
        statements=statements,
        has_rollback=has_rollback,
        has_transaction=has_txn,
        filename=os.path.basename(path),
    )


# ── Django parser ────────────────────────────────────────────────────────────

def _parse_django(path: str, content: str) -> ParsedMigration:
    """
    Extract SQL-like intent from Django migration operations.
    We reconstruct pseudo-SQL from the operations list for rule checking.
    """
    pseudo_sql_parts = []

    # AddField
    for m in re.finditer(
        r"AddField\s*\([^)]*model_name\s*=\s*['\"](\w+)['\"][^)]*"
        r"name\s*=\s*['\"](\w+)['\"][^)]*field\s*=\s*([^,\)]+)",
        content, re.DOTALL | re.IGNORECASE
    ):
        model, col, field_def = m.group(1), m.group(2), m.group(3)
        null_allowed = "null=True" in field_def or "blank=True" in field_def
        has_default = "default=" in field_def
        not_null_clause = "" if null_allowed or has_default else " NOT NULL"
        pseudo_sql_parts.append(
            f"ALTER TABLE {model} ADD COLUMN {col}{not_null_clause};"
        )
        # FK detection
        if "ForeignKey" in field_def or "OneToOneField" in field_def:
            pseudo_sql_parts.append(f"-- FK: {model}.{col} needs index")

    # RemoveField → DROP COLUMN
    for m in re.finditer(
        r"RemoveField\s*\([^)]*model_name\s*=\s*['\"](\w+)['\"][^)]*"
        r"name\s*=\s*['\"](\w+)['\"]",
        content, re.DOTALL | re.IGNORECASE
    ):
        pseudo_sql_parts.append(f"ALTER TABLE {m.group(1)} DROP COLUMN {m.group(2)};")

    # DeleteModel → DROP TABLE
    for m in re.finditer(
        r"DeleteModel\s*\([^)]*name\s*=\s*['\"](\w+)['\"]",
        content, re.DOTALL | re.IGNORECASE
    ):
        pseudo_sql_parts.append(f"DROP TABLE {m.group(1)};")

    # RenameField
    for m in re.finditer(
        r"RenameField\s*\([^)]*model_name\s*=\s*['\"](\w+)['\"][^)]*"
        r"old_name\s*=\s*['\"](\w+)['\"][^)]*new_name\s*=\s*['\"](\w+)['\"]",
        content, re.DOTALL | re.IGNORECASE
    ):
        pseudo_sql_parts.append(
            f"ALTER TABLE {m.group(1)} RENAME COLUMN {m.group(2)} TO {m.group(3)};"
        )

    # RenameModel
    for m in re.finditer(
        r"RenameModel\s*\([^)]*old_name\s*=\s*['\"](\w+)['\"][^)]*"
        r"new_name\s*=\s*['\"](\w+)['\"]",
        content, re.DOTALL | re.IGNORECASE
    ):
        pseudo_sql_parts.append(f"RENAME TABLE {m.group(1)} TO {m.group(2)};")

    # RunSQL — extract raw SQL
    for m in re.finditer(r"RunSQL\s*\(\s*(['\"])(.*?)\1", content, re.DOTALL):
        pseudo_sql_parts.append(m.group(2))

    up_sql = "\n".join(pseudo_sql_parts)
    has_rollback = "reverse_migrations" in content.lower() or (
        re.search(r"migrations\.RunSQL\s*\([^,]+,\s*['\"]", content) is not None
    )

    return ParsedMigration(
        path=path,
        format=MigrationFormat.DJANGO,
        raw=content,
        up_sql=up_sql,
        down_sql="",
        statements=_split_statements(up_sql),
        has_rollback=has_rollback,
        has_transaction=True,  # Django wraps in atomic by default
        filename=os.path.basename(path),
    )


# ── Alembic parser ───────────────────────────────────────────────────────────

def _parse_alembic(path: str, content: str) -> ParsedMigration:
    """Extract pseudo-SQL from Alembic migration upgrade/downgrade functions."""
    pseudo_sql_parts = []

    # add_column
    for m in re.finditer(
        r"op\.add_column\s*\(\s*['\"](\w+)['\"],\s*sa\.Column\s*\(\s*['\"](\w+)['\"],\s*([^,\)]+)(.*?)\)",
        content, re.DOTALL
    ):
        table, col, col_type, rest = m.group(1), m.group(2), m.group(3), m.group(4)
        nullable = "nullable=True" in rest
        has_server_default = "server_default=" in rest
        not_null = "" if nullable or has_server_default else " NOT NULL"
        pseudo_sql_parts.append(f"ALTER TABLE {table} ADD COLUMN {col}{not_null};")

    # drop_column
    for m in re.finditer(
        r"op\.drop_column\s*\(\s*['\"](\w+)['\"],\s*['\"](\w+)['\"]",
        content
    ):
        pseudo_sql_parts.append(f"ALTER TABLE {m.group(1)} DROP COLUMN {m.group(2)};")

    # drop_table
    for m in re.finditer(r"op\.drop_table\s*\(\s*['\"](\w+)['\"]", content):
        pseudo_sql_parts.append(f"DROP TABLE {m.group(1)};")

    # rename column / table
    for m in re.finditer(
        r"op\.alter_column\s*\(\s*['\"](\w+)['\"],\s*['\"](\w+)['\"][^)]*new_column_name\s*=\s*['\"](\w+)['\"]",
        content
    ):
        pseudo_sql_parts.append(
            f"ALTER TABLE {m.group(1)} RENAME COLUMN {m.group(2)} TO {m.group(3)};"
        )

    for m in re.finditer(
        r"op\.rename_table\s*\(\s*['\"](\w+)['\"],\s*['\"](\w+)['\"]", content
    ):
        pseudo_sql_parts.append(f"RENAME TABLE {m.group(1)} TO {m.group(2)};")

    # create_index without concurrently
    for m in re.finditer(
        r"op\.create_index\s*\(([^)]+)\)", content
    ):
        args = m.group(1)
        if "postgresql_concurrently" not in args and "concurrently" not in args.lower():
            pseudo_sql_parts.append("CREATE INDEX without CONCURRENTLY;")

    # execute raw SQL
    for m in re.finditer(r"op\.execute\s*\(\s*['\"]([^'\"]+)['\"]", content):
        pseudo_sql_parts.append(m.group(1))

    # check for downgrade function
    has_rollback = bool(re.search(r"def downgrade", content))

    up_sql = "\n".join(pseudo_sql_parts)
    return ParsedMigration(
        path=path,
        format=MigrationFormat.ALEMBIC,
        raw=content,
        up_sql=up_sql,
        down_sql="",
        statements=_split_statements(up_sql),
        has_rollback=has_rollback,
        has_transaction=True,  # Alembic uses transaction by default
        filename=os.path.basename(path),
    )


# ── Format detection ─────────────────────────────────────────────────────────

def _detect_format(path: str, content: str) -> MigrationFormat:
    if path.endswith(".sql"):
        return MigrationFormat.SQL
    if path.endswith(".py"):
        if "from django.db import migrations" in content or "class Migration" in content:
            return MigrationFormat.DJANGO
        if "from alembic import op" in content or "import alembic" in content or "def upgrade" in content:
            return MigrationFormat.ALEMBIC
    return MigrationFormat.UNKNOWN


# ── Public API ───────────────────────────────────────────────────────────────

def parse(path: str) -> ParsedMigration:
    """Parse a migration file and return a ParsedMigration."""
    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read()

    fmt = _detect_format(path, content)

    if fmt == MigrationFormat.SQL:
        return _parse_sql(path, content)
    elif fmt == MigrationFormat.DJANGO:
        return _parse_django(path, content)
    elif fmt == MigrationFormat.ALEMBIC:
        return _parse_alembic(path, content)
    else:
        # Try SQL parsing as fallback
        return _parse_sql(path, content)
