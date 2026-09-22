from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from alembic import command

POSTGRES_TEST_URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_TEST_URL, reason="POSTGRES_TEST_URL is not configured")
ROOT = Path(__file__).resolve().parents[3]


def test_fresh_postgresql_migration_foreign_keys_and_unique_constraints():
    schema = f"huce_test_{uuid4().hex}"
    admin = sa.create_engine(POSTGRES_TEST_URL)
    url = make_url(POSTGRES_TEST_URL).update_query_dict({"options": f"-csearch_path={schema}"})
    scoped = sa.create_engine(url)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        config = Config("alembic.ini")
        config.set_main_option(
            "sqlalchemy.url",
            url.render_as_string(hide_password=False).replace("%", "%%"),
        )
        command.upgrade(config, "head")
        inspector = sa.inspect(scoped)
        assert "classes" in inspector.get_table_names()
        assert "lecturer_course_capabilities" in inspector.get_table_names()
        unique_sets = {
            tuple(item["column_names"]) for item in inspector.get_unique_constraints("classes")
        }
        assert ("semester_id", "course_id", "class_code") in unique_sets
        classes = sa.Table("classes", sa.MetaData(), autoload_with=scoped)
        with pytest.raises(IntegrityError):
            with scoped.begin() as connection:
                connection.execute(
                    classes.insert().values(
                        semester_id=999999,
                        course_id=999999,
                        class_code="FK-REJECT",
                        credits=0,
                        merged_confirmed=False,
                        merge_status="single",
                        locked_assignment=False,
                        source_file="test",
                        source_sheet="S",
                        source_row=1,
                        raw_values={},
                    )
                )
        semesters = sa.Table("semesters", sa.MetaData(), autoload_with=scoped)
        courses = sa.Table("courses", sa.MetaData(), autoload_with=scoped)
        with scoped.begin() as connection:
            semester_id = connection.execute(
                semesters.insert()
                .values(
                    name="PostgreSQL test",
                    department_name="Department",
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 6, 1),
                    head_name="Head",
                    status="draft",
                    is_active=True,
                    created_at=sa.func.now(),
                )
                .returning(semesters.c.id)
            ).scalar_one()
            course_id = connection.execute(
                courses.insert().values(code="PG-C", name="Course").returning(courses.c.id)
            ).scalar_one()
            class_values = {
                "semester_id": semester_id,
                "course_id": course_id,
                "class_code": "PG-UNIQUE",
                "credits": 3,
                "merged_confirmed": False,
                "merge_status": "single",
                "locked_assignment": False,
                "source_file": "test",
                "source_sheet": "S",
                "source_row": 1,
                "raw_values": {},
            }
            connection.execute(classes.insert().values(**class_values))
        with pytest.raises(IntegrityError):
            with scoped.begin() as connection:
                connection.execute(classes.insert().values(**class_values))
        with scoped.connect() as connection:
            version = connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert version == "0009_department_agnostic_capabilities"
        version_column = next(
            column for column in inspector.get_columns("alembic_version")
            if column["name"] == "version_num"
        )
        assert version_column["type"].length >= len(version)

        token = "postgres-runtime-test-token"
        environment = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "apps/api"),
            "ENVIRONMENT": "staging",
            "DATABASE_URL": url.render_as_string(hide_password=False),
            "ALLOWED_ORIGINS": "https://staging.example.invalid",
            "STORAGE_BACKEND": "s3",
            "S3_BUCKET": "private",
            "S3_REGION": "test",
            "S3_ACCESS_KEY_ID": "test",
            "S3_SECRET_ACCESS_KEY": "test",
            "INTERNAL_API_TOKEN": token,
            "RUN_MIGRATIONS_ON_STARTUP": "false",
        }
        smoke_script = f"""
from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as client:
    assert client.get('/api/v1/health').status_code == 200
    response = client.get(
        '/api/v1/semesters',
        headers={{'x-internal-api-key': '{token}'}},
    )
    assert response.status_code == 200, response.text
"""
        smoke = subprocess.run(
            [
                sys.executable,
                "-c",
                smoke_script,
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert smoke.returncode == 0, smoke.stdout + smoke.stderr
    finally:
        scoped.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin.dispose()
