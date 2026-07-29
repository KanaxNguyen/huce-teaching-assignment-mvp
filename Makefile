.PHONY: install dev api web test import docker

install:
	pnpm install
	python -m pip install -e "apps/api[dev]"

dev:
	docker compose up --build

api:
	python -m uvicorn app.main:app --app-dir apps/api --reload

web:
	pnpm --filter @huce/web dev

test:
	python -m pytest apps/api/tests
	pnpm test

import:
	python scripts/import-source-files.py

docker:
	docker compose up --build

