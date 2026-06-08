# migration-guard 🛡️

[![tests](https://github.com/MONISMALIK1/migration-guard/actions/workflows/tests.yml/badge.svg)](https://github.com/MONISMALIK1/migration-guard/actions/workflows/tests.yml)

**Catch dangerous database migrations before they reach production. No SaaS. No sign-up. One CLI.**

Your engineer added `NOT NULL` to a 50M-row table with no default and no rollback. The migration locked the table for 4 hours. Production was down.

`migration-guard` catches it in 2 seconds — before the PR merges.

```bash
migration-guard check migrations/0042_add_score.sql

# migration-guard — Risk Report
# File    : 0042_add_score.sql
# ────────────────────────────────────────────────────────────
#
#   Risk Level: ██████████ CRITICAL
#
#   ✗  NOT NULL column added without DEFAULT
#      Will lock the entire table during migration
#
#   ✗  No rollback / DOWN migration found
#      Cannot undo if deployment fails
#
#   ✗  DROP COLUMN 'legacy_status' detected
#      Ensure no code still references this column
#
#   ⚠  CREATE INDEX without CONCURRENTLY
#      Will lock table for writes during index build
#
# ────────────────────────────────────────────────────────────
#   Result: BLOCKED (2 critical issues) — fix before merging
```

---

## Install

Install from GitHub (not yet published to PyPI):

```bash
pip install "git+https://github.com/MONISMALIK1/migration-guard.git"

# With YAML config support:
pip install "migration-guard[yaml] @ git+https://github.com/MONISMALIK1/migration-guard.git"
```

Or from a clone: `git clone … && cd migration-guard && pip install ".[yaml]"`.

---

## Commands

### `check` — Inspect a single file

```bash
migration-guard check migrations/0042_add_score.sql
migration-guard check migrations/0042_add_score.sql --verbose   # show fix suggestions
migration-guard check migrations/0042_add_score.sql --fail-on high
```

### `scan` — Scan an entire directory

```bash
migration-guard scan migrations/
migration-guard scan migrations/ --fail-on high --json-report report.json
migration-guard scan . --no-recursive
```

---

## What It Catches

| Rule | Severity | What it detects |
|---|---|---|
| `NOT_NULL_NO_DEFAULT` | 🔴 Critical | `ADD COLUMN NOT NULL` without `DEFAULT` — table lock during backfill |
| `DROP_TABLE` | 🔴 Critical | `DROP TABLE` — irreversible without backup |
| `TRUNCATE` | 🔴 Critical | `TRUNCATE` — deletes all data immediately |
| `NO_ROLLBACK` | 🔴 Critical | No down/rollback migration found |
| `DROP_COLUMN` | 🟠 High | `DROP COLUMN` — code may still reference it |
| `RENAME_TABLE` | 🟠 High | `RENAME TABLE` — breaks all existing queries |
| `RENAME_COLUMN` | 🟠 High | `RENAME COLUMN` — breaks ORM + raw queries |
| `COLUMN_TYPE_CHANGE` | 🟠 High | `ALTER COLUMN TYPE` — may require full table rewrite |
| `MISSING_FK_INDEX` | 🟡 Medium | FK column added without an index |
| `NO_TRANSACTION` | 🟡 Medium | Multi-statement migration not in a transaction |
| `CONSTRAINT_WITHOUT_NOT_VALID` | 🟡 Medium | Constraint added without `NOT VALID` — validates all rows |
| `INDEX_WITHOUT_CONCURRENTLY` | 🔵 Low | `CREATE INDEX` without `CONCURRENTLY` — table lock |

---

## Supported Formats

| Format | How |
|---|---|
| **Raw SQL** | `.sql` files with optional `-- Down` / `-- +migrate Down` / `-- rollback` sections |
| **Django** | `.py` migration files — reads `AddField`, `RemoveField`, `DeleteModel`, `RenameField`, `RenameModel`, `RunSQL` |
| **Alembic** | `.py` files — reads `op.add_column`, `op.drop_column`, `op.drop_table`, `op.rename_table`, `op.execute` |

---

## Config File

Place `.migration-guard.yaml` in your repo root — `migration-guard` finds it automatically:

```yaml
# Minimum severity to fail CI
fail_on: high   # low / medium / high / critical

# Skip specific rules
skip_rules:
  - NO_ROLLBACK              # if your team doesn't use rollback migrations
  - INDEX_WITHOUT_CONCURRENTLY  # if not on PostgreSQL

# Show fix suggestions
verbose: false
```

---

## GitHub Actions

Triggers automatically on PRs that touch migration files:

```yaml
name: Migration Safety Check
on:
  pull_request:
    paths: ['migrations/**', '**/migrations/**']

jobs:
  migration-guard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with: { python-version: '3.12' }
      - run: pip install "git+https://github.com/MONISMALIK1/migration-guard.git"
      - run: migration-guard scan migrations/ --fail-on high --verbose
```

Violations appear as **red ✗ annotations** directly in the PR diff — reviewers see the risk without reading the SQL.

---

## Fix Suggestions

Run with `--verbose` to get a suggested fix for every issue:

```
  ✗  NOT NULL column added without DEFAULT
     → Add a DEFAULT value, or use a 3-step approach:
       (1) add column nullable, (2) backfill, (3) add NOT NULL constraint.

  ⚠  CREATE INDEX without CONCURRENTLY
     → Use CREATE INDEX CONCURRENTLY to build the index without locking.
```

---

## Architecture

```
migration_guard/
├── parser.py    # SQL + Django + Alembic migration parser
├── rules.py     # 12 risk rules — each returns RuleViolation list
├── scorer.py    # Overall risk level: LOW / MEDIUM / HIGH / CRITICAL
├── reporter.py  # Terminal report + JSON + GitHub Actions annotations
├── scanner.py   # Directory walker — finds migration files
├── config.py    # .migration-guard.yaml loader
└── cli.py       # Click CLI — check / scan
```

**Design decisions:**
- **Zero infra** — reads files, prints results, done
- **No DB connection needed** — static analysis only
- **Stdlib only** — `click` is the only required dep
- **Exit codes** — `0` = safe, `1` = risk found — CI-friendly

---

## Running Tests

```bash
pip install pytest click
pytest tests/ -v   # 42 tests, no external dependencies
```

---

## Related

- [agent-watchdog](https://github.com/MONISMALIK1/agent-watchdog) — loop detection + cost kill switch for LLM agents
- [prompt-sentinel](https://github.com/MONISMALIK1/prompt-sentinel) — regression testing for LLM prompts
- [stripe-reconciler](https://github.com/MONISMALIK1/stripe-reconciler) — diff Stripe against your database

---

## License

MIT — Monis Malik
