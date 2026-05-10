"""Tests for the Click CLI."""

import json
import os
import tempfile
import pytest
from click.testing import CliRunner
from migration_guard.cli import cli


def write_tmp(content: str, suffix: str = ".sql") -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False)
    f.write(content)
    f.close()
    return f.name


class TestCheckCommand:
    def setup_method(self):
        self.runner = CliRunner()

    def test_clean_migration_exits_0(self):
        path = write_tmp(
            "-- +migrate Up\nCREATE TABLE foo (id SERIAL PRIMARY KEY);\n-- +migrate Down\nDROP TABLE foo;"
        )
        try:
            result = self.runner.invoke(cli, ["check", path])
            assert result.exit_code == 0, result.output
            assert "CLEAN" in result.output or "No issues" in result.output
        finally:
            os.unlink(path)

    def test_critical_migration_exits_1(self):
        path = write_tmp("DROP TABLE users;")
        try:
            result = self.runner.invoke(cli, ["check", path])
            assert result.exit_code == 1
            assert "DROP_TABLE" in result.output or "DROP TABLE" in result.output
        finally:
            os.unlink(path)

    def test_fail_on_medium_exits_1(self):
        # CREATE INDEX without CONCURRENTLY = LOW, but NO_TRANSACTION = MEDIUM
        path = write_tmp(
            "CREATE TABLE a (id INT);\nCREATE TABLE b (id INT);"
        )
        try:
            result = self.runner.invoke(cli, ["check", path, "--fail-on", "medium"])
            assert result.exit_code == 1
        finally:
            os.unlink(path)

    def test_fail_on_high_allows_medium(self):
        # Multi-statement with no transaction = MEDIUM (NO_TRANSACTION)
        # Skip NO_ROLLBACK so only MEDIUM violations remain → should pass with --fail-on high
        path = write_tmp(
            "CREATE TABLE a (id INT);\nCREATE TABLE b (id INT);"
        )
        try:
            result = self.runner.invoke(cli, [
                "check", path, "--fail-on", "high", "--skip-rule", "NO_ROLLBACK"
            ])
            assert result.exit_code == 0
        finally:
            os.unlink(path)

    def test_skip_rule(self):
        path = write_tmp("DROP TABLE users;")
        try:
            result = self.runner.invoke(cli, [
                "check", path, "--skip-rule", "DROP_TABLE", "--skip-rule", "NO_ROLLBACK"
            ])
            assert result.exit_code == 0
        finally:
            os.unlink(path)

    def test_verbose_shows_suggestion(self):
        path = write_tmp("ALTER TABLE users ADD COLUMN score INT NOT NULL;")
        try:
            result = self.runner.invoke(cli, ["check", path, "--verbose"])
            assert "→" in result.output or "3-step" in result.output or "suggestion" in result.output.lower() or "DEFAULT" in result.output
        finally:
            os.unlink(path)

    def test_writes_json_report(self):
        path = write_tmp("DROP TABLE users;")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as jf:
            json_path = jf.name
        try:
            self.runner.invoke(cli, ["check", path, "--json-report", json_path])
            assert os.path.exists(json_path)
            with open(json_path) as f:
                data = json.load(f)
            assert "files" in data
            assert "summary" in data
        finally:
            os.unlink(path)
            if os.path.exists(json_path):
                os.unlink(json_path)

    def test_help_text(self):
        result = self.runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "migration-guard" in result.output


class TestScanCommand:
    def setup_method(self):
        self.runner = CliRunner()

    def _make_tmpdir_with_migrations(self, files: dict) -> str:
        d = tempfile.mkdtemp()
        for name, content in files.items():
            with open(os.path.join(d, name), "w") as f:
                f.write(content)
        return d

    def test_scan_clean_directory_exits_0(self):
        d = self._make_tmpdir_with_migrations({
            "0001_create_users.sql": (
                "-- +migrate Up\nCREATE TABLE users (id SERIAL);\n"
                "-- +migrate Down\nDROP TABLE users;"
            ),
        })
        try:
            result = self.runner.invoke(cli, ["scan", d])
            assert result.exit_code == 0, result.output
        finally:
            import shutil; shutil.rmtree(d)

    def test_scan_flags_risky_migration(self):
        d = self._make_tmpdir_with_migrations({
            "0001_drop_table.sql": "DROP TABLE users;",
        })
        try:
            result = self.runner.invoke(cli, ["scan", d])
            assert result.exit_code == 1
            assert "CRITICAL" in result.output or "DROP" in result.output
        finally:
            import shutil; shutil.rmtree(d)

    def test_scan_empty_directory(self):
        d = tempfile.mkdtemp()
        try:
            result = self.runner.invoke(cli, ["scan", d])
            assert result.exit_code == 0
            assert "No migration files found" in result.output
        finally:
            import shutil; shutil.rmtree(d)

    def test_scan_writes_json_report(self):
        d = self._make_tmpdir_with_migrations({
            "0001_create.sql": "-- +migrate Up\nCREATE TABLE a (id INT);\n-- +migrate Down\nDROP TABLE a;",
        })
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as jf:
            json_path = jf.name
        try:
            self.runner.invoke(cli, ["scan", d, "--json-report", json_path])
            with open(json_path) as f:
                data = json.load(f)
            assert data["summary"]["total"] >= 1
        finally:
            import shutil; shutil.rmtree(d)
            if os.path.exists(json_path):
                os.unlink(json_path)

    def test_scan_fail_on_high_passes_medium(self):
        # NO_TRANSACTION is MEDIUM — should pass with --fail-on high (skip NO_ROLLBACK to isolate)
        d = self._make_tmpdir_with_migrations({
            "0001_multi.sql": "CREATE TABLE a (id INT);\nCREATE TABLE b (id INT);",
        })
        try:
            result = self.runner.invoke(cli, [
                "scan", d, "--fail-on", "high", "--skip-rule", "NO_ROLLBACK"
            ])
            assert result.exit_code == 0
        finally:
            import shutil; shutil.rmtree(d)
