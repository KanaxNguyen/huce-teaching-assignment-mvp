#!/bin/sh
set -e
# The free Space disk is ephemeral: the schema lives in Postgres, so bring it up to date on every start.
# alembic is idempotent; set MIGRATE_ON_BOOT=0 to skip it.
if [ "${MIGRATE_ON_BOOT:-1}" = "1" ]; then
  alembic -c alembic.ini upgrade head
fi
exec uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port "${PORT:-7860}"
