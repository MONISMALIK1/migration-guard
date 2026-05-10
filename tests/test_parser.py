"""Tests for migration file parser."""

import os
import tempfile
import pytest
from migration_guard.parser import parse, MigrationFormat, _strip_comments, _split_statements


def write_tmp(content: str, suffix: str = ".sql") -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False)
    f.write(content)
    f.close()
    return f.name


class TestStripComments:
    def test_strips_line_comments(self):
        sql = "SELECT 1; -- this is a comment\nSELECT 2;"
        result = _strip_comments(sql)
        assert "comment" not in result
        assert "SELECT 1" in result

    def test_strips_block_comments(self):
        sql = "SELECT /* block comment */ 1;"
        result = _strip_comments(sql)
        assert "block comment" not in result

    def test_preserves_statements(self):
        sql = "CREATE TABLE foo (id INT); -- done"
        result = _strip_comments(sql)
        assert "CREATE TABLE" in result


class TestSplitStatements:
    def test_splits_on_semicolon(self):
        sql = "CREATE TABLE a (id INT); CREATE TABLE b (id INT);"
        stmts = _split_statements(sql)
        assert len(stmts) == 2

    def test_empty_string(self):
        assert _split_statements("") == []

    def test_single_statement(self):
        stmts = _split_statements("SELECT 1;")
        assert len(stmts) == 1


class TestSQLParser:
    def test_parses_basic_sql(self):
        path = write_tmp("ALTER TABLE users ADD COLUMN age INT;")
        try:
            m = parse(path)
            assert m.format == MigrationFormat.SQL
            assert "ADD COLUMN" in m.up_sql
            assert len(m.statements) == 1
        finally:
            os.unlink(path)

    def test_detects_rollback_section(self):
        content = """
-- +migrate Up
CREATE TABLE foo (id SERIAL);

-- +migrate Down
DROP TABLE foo;
"""
        path = write_tmp(content)
        try:
            m = parse(path)
            assert m.has_rollback
            assert "DROP TABLE" in m.down_sql
        finally:
            os.unlink(path)

    def test_detects_down_keyword(self):
        content = """
CREATE TABLE foo (id SERIAL);
-- Down
DROP TABLE foo;
"""
        path = write_tmp(content)
        try:
            m = parse(path)
            assert m.has_rollback
        finally:
            os.unlink(path)

    def test_no_rollback_single_section(self):
        path = write_tmp("CREATE TABLE foo (id SERIAL);")
        try:
            m = parse(path)
            assert not m.has_rollback
        finally:
            os.unlink(path)

    def test_detects_transaction(self):
        content = "BEGIN;\nCREATE TABLE foo (id SERIAL);\nCOMMIT;"
        path = write_tmp(content)
        try:
            m = parse(path)
            assert m.has_transaction
        finally:
            os.unlink(path)

    def test_no_transaction_detected(self):
        path = write_tmp("CREATE TABLE foo (id SERIAL);")
        try:
            m = parse(path)
            assert not m.has_transaction
        finally:
            os.unlink(path)

    def test_multiple_statements(self):
        content = "CREATE TABLE a (id INT);\nCREATE TABLE b (id INT);\nCREATE TABLE c (id INT);"
        path = write_tmp(content)
        try:
            m = parse(path)
            assert len(m.statements) == 3
        finally:
            os.unlink(path)


class TestDjangoParser:
    def test_detects_django_format(self):
        content = """
from django.db import migrations, models

class Migration(migrations.Migration):
    operations = [
        migrations.AddField(
            model_name='user',
            name='age',
            field=models.IntegerField(null=True),
        ),
    ]
"""
        path = write_tmp(content, suffix=".py")
        try:
            m = parse(path)
            assert m.format == MigrationFormat.DJANGO
        finally:
            os.unlink(path)

    def test_add_field_not_null_generates_pseudo_sql(self):
        content = """
from django.db import migrations, models

class Migration(migrations.Migration):
    operations = [
        migrations.AddField(
            model_name='order',
            name='priority',
            field=models.IntegerField(),
        ),
    ]
"""
        path = write_tmp(content, suffix=".py")
        try:
            m = parse(path)
            assert "ADD COLUMN" in m.up_sql
            assert "NOT NULL" in m.up_sql
        finally:
            os.unlink(path)

    def test_add_field_nullable_no_not_null(self):
        content = """
from django.db import migrations, models

class Migration(migrations.Migration):
    operations = [
        migrations.AddField(
            model_name='user',
            name='bio',
            field=models.TextField(null=True, blank=True),
        ),
    ]
"""
        path = write_tmp(content, suffix=".py")
        try:
            m = parse(path)
            assert "NOT NULL" not in m.up_sql
        finally:
            os.unlink(path)

    def test_delete_model_generates_drop_table(self):
        content = """
from django.db import migrations

class Migration(migrations.Migration):
    operations = [
        migrations.DeleteModel(name='LegacyTable'),
    ]
"""
        path = write_tmp(content, suffix=".py")
        try:
            m = parse(path)
            assert "DROP TABLE" in m.up_sql
        finally:
            os.unlink(path)

    def test_remove_field_generates_drop_column(self):
        content = """
from django.db import migrations

class Migration(migrations.Migration):
    operations = [
        migrations.RemoveField(model_name='user', name='old_field'),
    ]
"""
        path = write_tmp(content, suffix=".py")
        try:
            m = parse(path)
            assert "DROP COLUMN" in m.up_sql
        finally:
            os.unlink(path)


class TestAlembicParser:
    def test_detects_alembic_format(self):
        content = """
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('users', sa.Column('age', sa.Integer(), nullable=True))

def downgrade():
    op.drop_column('users', 'age')
"""
        path = write_tmp(content, suffix=".py")
        try:
            m = parse(path)
            assert m.format == MigrationFormat.ALEMBIC
        finally:
            os.unlink(path)

    def test_alembic_has_rollback_when_downgrade_present(self):
        content = """
from alembic import op

def upgrade():
    op.add_column('users', None)

def downgrade():
    op.drop_column('users', 'age')
"""
        path = write_tmp(content, suffix=".py")
        try:
            m = parse(path)
            assert m.has_rollback
        finally:
            os.unlink(path)

    def test_alembic_no_rollback_without_downgrade(self):
        content = """
from alembic import op

def upgrade():
    op.drop_table('legacy')
"""
        path = write_tmp(content, suffix=".py")
        try:
            m = parse(path)
            assert not m.has_rollback
        finally:
            os.unlink(path)

    def test_alembic_drop_column_detected(self):
        content = """
from alembic import op

def upgrade():
    op.drop_column('users', 'old_field')

def downgrade():
    pass
"""
        path = write_tmp(content, suffix=".py")
        try:
            m = parse(path)
            assert "DROP COLUMN" in m.up_sql
        finally:
            os.unlink(path)
