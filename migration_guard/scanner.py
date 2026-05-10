"""Directory scanner — find and check all migration files."""

import os
from .parser import parse, MigrationFormat
from .rules import run_rules, Severity
from .scorer import score, MigrationScore

MIGRATION_EXTENSIONS = {".sql", ".py"}

MIGRATION_FILENAME_PATTERNS = [
    lambda f: f.endswith(".sql"),
    lambda f: f.endswith(".py") and (
        f[0].isdigit() or
        "migration" in f.lower() or
        f.startswith("V") or    # Flyway-style
        "__" in f               # Alembic-style
    ),
]


def _is_migration_file(path: str) -> bool:
    name = os.path.basename(path)
    # Skip Django __init__ and test files
    if name in ("__init__.py", "conftest.py"):
        return False
    ext = os.path.splitext(name)[1].lower()
    if ext not in MIGRATION_EXTENSIONS:
        return False
    return any(p(name) for p in MIGRATION_FILENAME_PATTERNS)


def scan_directory(
    directory: str,
    skip_rules: list[str] = None,
    min_severity: Severity = Severity.LOW,
    recursive: bool = True,
) -> list[MigrationScore]:
    """Scan a directory for migration files and return risk scores."""
    scores = []
    if recursive:
        for root, _, files in os.walk(directory):
            for fname in sorted(files):
                path = os.path.join(root, fname)
                if _is_migration_file(path):
                    scores.append(_check_file(path, skip_rules, min_severity))
    else:
        for fname in sorted(os.listdir(directory)):
            path = os.path.join(directory, fname)
            if os.path.isfile(path) and _is_migration_file(path):
                scores.append(_check_file(path, skip_rules, min_severity))
    return scores


def check_file(
    path: str,
    skip_rules: list[str] = None,
    min_severity: Severity = Severity.LOW,
) -> MigrationScore:
    return _check_file(path, skip_rules, min_severity)


def _check_file(
    path: str,
    skip_rules: list[str] = None,
    min_severity: Severity = Severity.LOW,
) -> MigrationScore:
    migration = parse(path)
    violations = run_rules(migration, skip_rules=skip_rules, min_severity=min_severity)
    return score(path, os.path.basename(path), violations)
