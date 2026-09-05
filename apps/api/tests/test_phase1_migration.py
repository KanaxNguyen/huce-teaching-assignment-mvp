import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


LEGACY_SQL = """
CREATE TABLE semesters (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL, department_name VARCHAR(200) NOT NULL, start_date DATE NOT NULL, end_date DATE NOT NULL, head_name VARCHAR(200) NOT NULL, status VARCHAR(30) NOT NULL, is_active BOOLEAN NOT NULL, created_at DATETIME NOT NULL);
CREATE TABLE lecturers (id INTEGER PRIMARY KEY, code VARCHAR(30) UNIQUE, canonical_name VARCHAR(200) UNIQUE NOT NULL, aliases JSON NOT NULL, confirmed BOOLEAN NOT NULL, max_credits FLOAT NOT NULL, source_file VARCHAR(300), source_sheet VARCHAR(100), source_row INTEGER);
CREATE TABLE courses (id INTEGER PRIMARY KEY, code VARCHAR(50) UNIQUE NOT NULL, name VARCHAR(300) NOT NULL);
CREATE TABLE classes (id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL, class_code VARCHAR(100) NOT NULL, credits FLOAT NOT NULL, merged_group_id VARCHAR(100), merged_confirmed BOOLEAN NOT NULL, locked_assignment BOOLEAN NOT NULL, assigned_lecturer_id INTEGER, source_file VARCHAR(300) NOT NULL, source_sheet VARCHAR(100) NOT NULL, source_row INTEGER NOT NULL, raw_values JSON NOT NULL, UNIQUE(course_id,class_code), FOREIGN KEY(course_id) REFERENCES courses(id), FOREIGN KEY(assigned_lecturer_id) REFERENCES lecturers(id));
CREATE TABLE sessions (id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL, weekday INTEGER NOT NULL, start_period INTEGER NOT NULL, end_period INTEGER NOT NULL, room VARCHAR(200) NOT NULL, start_date DATE, end_date DATE, raw_weeks VARCHAR(80) NOT NULL, active_weeks JSON NOT NULL, source_row INTEGER NOT NULL, FOREIGN KEY(class_id) REFERENCES classes(id));
CREATE TABLE constraints (id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL, constraint_type VARCHAR(50) NOT NULL, hardness VARCHAR(10) NOT NULL, weight FLOAT NOT NULL, lecturer_id INTEGER, target JSON NOT NULL, raw_text TEXT, confirmed BOOLEAN NOT NULL, active BOOLEAN NOT NULL);
CREATE TABLE seminars (id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL, chair_name VARCHAR(200) NOT NULL, members JSON NOT NULL, alternatives JSON NOT NULL, weight FLOAT NOT NULL, hardness VARCHAR(10) NOT NULL);
CREATE TABLE validation_issues (id INTEGER PRIMARY KEY, severity VARCHAR(20) NOT NULL, code VARCHAR(60) NOT NULL, message TEXT NOT NULL, source_file VARCHAR(300), source_sheet VARCHAR(100), source_row INTEGER, field VARCHAR(100), raw_value TEXT, suggestion TEXT);
CREATE TABLE optimization_runs (id INTEGER PRIMARY KEY, created_at DATETIME NOT NULL, status VARCHAR(30) NOT NULL, score FLOAT, summary JSON NOT NULL);
CREATE TABLE assignments (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, class_id INTEGER NOT NULL, lecturer_id INTEGER NOT NULL, locked BOOLEAN NOT NULL, penalty FLOAT NOT NULL, UNIQUE(run_id,class_id));
CREATE TABLE import_batches (id INTEGER PRIMARY KEY, created_at DATETIME NOT NULL, source_files JSON NOT NULL, summary JSON NOT NULL);
CREATE TABLE output_template_profiles (id INTEGER PRIMARY KEY, semester_id INTEGER, source_file VARCHAR(300) NOT NULL, source_sheet VARCHAR(100) NOT NULL, header_row INTEGER NOT NULL, mappings JSON NOT NULL, missing_fields JSON NOT NULL, preview JSON NOT NULL, created_at DATETIME NOT NULL);
INSERT INTO semesters VALUES (7,'Legacy','D','2026-01-01','2026-06-01','H','active',1,CURRENT_TIMESTAMP);
INSERT INTO lecturers VALUES (1,'GV01','Teacher One','[]',1,24,NULL,NULL,NULL);
INSERT INTO courses VALUES (1,'MATH','Math');
INSERT INTO classes VALUES (1,1,'L1',3,NULL,0,1,1,'legacy.xls','S',3,'{}');
INSERT INTO sessions VALUES (1,1,2,1,3,'P1',NULL,NULL,'123','[1,2,3]',3);
INSERT INTO constraints VALUES (1,'C','unavailable','soft',0.8,1,'{}',NULL,1,1);
INSERT INTO optimization_runs VALUES (1,CURRENT_TIMESTAMP,'optimal',0,'{}');
INSERT INTO assignments VALUES (1,1,1,1,0,0);
INSERT INTO import_batches VALUES (1,CURRENT_TIMESTAMP,'["legacy.xls"]','{}');
INSERT INTO output_template_profiles VALUES (1,NULL,'legacy.xlsx','S',1,'{}','[]','[]',CURRENT_TIMESTAMP);
"""


def test_legacy_database_upgrades_to_phase1(tmp_path):
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.executescript(LEGACY_SQL)
    connection.commit(); connection.close()

    root = Path(__file__).resolve().parents[3]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")

    migrated = create_engine(f"sqlite:///{database}")
    with migrated.connect() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0004_v11_merge_status"
        assert "merge_status" in {column["name"] for column in inspect(db).get_columns("classes")}
        assert "lecturer_course_capabilities" in inspect(db).get_table_names()
        for table in ("classes", "constraints", "optimization_runs", "assignments", "import_batches", "output_template_profiles"):
            assert "semester_id" in {column["name"] for column in inspect(db).get_columns(table)}
            assert db.scalar(text(f"SELECT semester_id FROM {table} LIMIT 1")) == 7
        assert db.scalar(text("SELECT canonical_name FROM lecturers WHERE id=1")) == "Teacher One"
        assert db.scalar(text("SELECT class_code FROM classes WHERE id=1")) == "L1"


def test_interrupted_human_in_loop_migration_resumes_safely(tmp_path):
    database = tmp_path / "partial-0003.db"
    connection = sqlite3.connect(database)
    connection.executescript(LEGACY_SQL)
    connection.commit(); connection.close()
    root = Path(__file__).resolve().parents[3]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "0002_domain_correctness")
    # Simulate the exact partially-applied SQLite state found by release UAT.
    connection = sqlite3.connect(database)
    connection.execute("ALTER TABLE classes ADD COLUMN assignment_source VARCHAR(20)")
    connection.commit(); connection.close()
    command.upgrade(config, "head")
    migrated = create_engine(f"sqlite:///{database}")
    with migrated.connect() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0004_v11_merge_status"
        assert "source" in {column["name"] for column in inspect(db).get_columns("assignments")}


def test_merge_status_migration_backfills_existing_review_decisions(tmp_path):
    database = tmp_path / "merge-status.db"
    connection = sqlite3.connect(database)
    connection.executescript(LEGACY_SQL)
    connection.commit(); connection.close()
    root = Path(__file__).resolve().parents[3]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "0003_human_in_loop")
    with sqlite3.connect(database) as db:
        db.execute("UPDATE classes SET merged_group_id='M-1', merged_confirmed=1")
    command.upgrade(config, "head")
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT merge_status FROM classes").fetchone() == ("confirmed",)
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("0004_v11_merge_status",)
