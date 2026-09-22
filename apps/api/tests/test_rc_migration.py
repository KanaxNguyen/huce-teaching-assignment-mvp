"""Release migration checks against persistent SQLite, never the live DB."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from test_phase1_migration import LEGACY_SQL

ROOT = Path(__file__).resolve().parents[3]
HEAD = "0009_department_agnostic_capabilities"


def upgrade(path, revision="head"):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "apps/api/alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, revision)


def snapshot(path):
    with sqlite3.connect(path) as db:
        return {
            name: (tuple(row[1] for row in db.execute(f'PRAGMA table_info("{name}")')),
                   db.execute(f'SELECT * FROM "{name}" ORDER BY id').fetchall())
            for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('alembic_version','sqlite_sequence')").fetchall()
        }


def assert_preserved(path, before):
    with sqlite3.connect(path) as db:
        for table, (columns, rows) in before.items():
            names = ','.join(f'"{column}"' for column in columns)
            assert db.execute(f'SELECT {names} FROM "{table}" ORDER BY id').fetchall() == rows
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("SELECT version_num FROM alembic_version").fetchall() == [(HEAD,)]


def legacy_at_0002(path):
    with sqlite3.connect(path) as db:
        db.executescript(LEGACY_SQL)
    upgrade(path, "0001_semester_isolation")
    upgrade(path, "0002_domain_correctness")
    with sqlite3.connect(path) as db:
        assert 'assignment_source' not in {r[1] for r in db.execute('PRAGMA table_info(classes)')}
        assert 'source' not in {r[1] for r in db.execute('PRAGMA table_info(assignments)')}


def test_fresh_database_migration_and_repeat(tmp_path):
    path = tmp_path / "fresh.db"
    upgrade(path, "0001_semester_isolation")
    with sqlite3.connect(path) as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='lecturer_course_capabilities'").fetchall()
        assert 'assignment_source' not in {r[1] for r in db.execute('PRAGMA table_info(classes)')}
    upgrade(path)
    before = snapshot(path)
    upgrade(path)
    assert_preserved(path, before)
    with sqlite3.connect(path) as db:
        columns = {row[1]: row for row in db.execute("PRAGMA table_info(normalized_preference_drafts)")}
        assert columns["context_type"][3] == 0
        assert columns["context_confirmed"][3] == 1
        foreign_keys = {row[3] for row in db.execute("PRAGMA foreign_key_list(normalized_preference_drafts)")}
        assert {"semester_id", "import_batch_id", "lecturer_id", "applied_constraint_id", "applied_seminar_id"} <= foreign_keys


def test_0002_rows_defaults_and_foreign_keys_preserved(tmp_path):
    path = tmp_path / "official-0002.db"
    legacy_at_0002(path)
    before = snapshot(path)
    upgrade(path)
    assert_preserved(path, before)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT source FROM assignments').fetchall() == [('SOLVER',)]
        assert db.execute('SELECT assignment_source FROM classes').fetchall() == [(None,)]
        assert db.execute('SELECT merge_status FROM classes').fetchall() == [('single',)]
        info = {r[1]: r for r in db.execute('PRAGMA table_info(assignments)')}
        assert info['source'][3] == 1
        assert info['source'][4] == "'SOLVER'"
        db.execute('INSERT INTO optimization_runs(id,semester_id,created_at,status,summary) VALUES (2,7,CURRENT_TIMESTAMP,\'optimal\',\'{}\')')
        db.execute('INSERT INTO assignments(id,semester_id,run_id,class_id,lecturer_id,locked,penalty) VALUES (2,7,2,1,1,0,0)')
        assert db.execute('SELECT source FROM assignments WHERE id=2').fetchone() == ('SOLVER',)


@pytest.mark.parametrize('partial', ['class_only', 'both', 'nullable_source'])
def test_partial_0003_recovery_preserves_manual_source(tmp_path, partial):
    path = tmp_path / f'{partial}.db'
    legacy_at_0002(path)
    with sqlite3.connect(path) as db:
        db.execute('ALTER TABLE classes ADD COLUMN assignment_source VARCHAR(20)')
        db.execute("UPDATE classes SET assignment_source='MANUAL'")
        if partial == 'both':
            db.execute("ALTER TABLE assignments ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'SOLVER'")
            db.execute("UPDATE assignments SET source='MANUAL'")
        elif partial == 'nullable_source':
            db.execute('ALTER TABLE assignments ADD COLUMN source VARCHAR(20)')
    before = snapshot(path)
    # NULL source is the only intentional data change during recovery.
    if partial == 'nullable_source':
        columns, rows = before['assignments']
        before['assignments'] = (columns[:-1], [row[:-1] for row in rows])
    upgrade(path)
    assert_preserved(path, before)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT assignment_source FROM classes').fetchone() == ('MANUAL',)
        assert db.execute('SELECT source FROM assignments').fetchone() == ('MANUAL' if partial == 'both' else 'SOLVER',)
        assert {r[1]: r for r in db.execute('PRAGMA table_info(assignments)')}['source'][3] == 1


@pytest.mark.parametrize('database_kind', ['fresh', 'official_0002', 'partial_0003'])
def test_persistent_api_startup_health_and_restart(tmp_path, database_kind):
    path = tmp_path / f'{database_kind}.db'
    if database_kind != 'fresh':
        legacy_at_0002(path)
    if database_kind == 'partial_0003':
        with sqlite3.connect(path) as db:
            db.execute('ALTER TABLE classes ADD COLUMN assignment_source VARCHAR(20)')
            db.execute("UPDATE classes SET assignment_source='MANUAL'")
            db.execute("ALTER TABLE assignments ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'SOLVER'")
            db.execute("UPDATE assignments SET source='MANUAL'")
    before = snapshot(path)
    script = '''
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app
from app.db.session import engine
for restart in range(2):
    with TestClient(app, raise_server_exceptions=True) as client:
        response = client.get('/api/v1/health')
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'ok'
        with engine.connect() as db:
            assert db.scalar(text('SELECT version_num FROM alembic_version')) == '0009_department_agnostic_capabilities'
            assert db.scalar(text('PRAGMA foreign_keys')) == 1
        assert client.get('/api/v1/semesters').status_code == 200
print('STARTUP_AND_RESTART_HEALTH_PASS')
'''
    environment = {**os.environ, 'DATABASE_URL': f'sqlite:///{path}', 'PYTHONPATH': str(ROOT / 'apps/api'),
                   'UPLOAD_DIR': str(tmp_path / 'uploads'), 'EXPORT_DIR': str(tmp_path / 'exports')}
    result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=environment, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'STARTUP_AND_RESTART_HEALTH_PASS' in result.stdout
    assert_preserved(path, before)
