# API

Base URL: `http://127.0.0.1:8000/api/v1`

- `GET /health` — health and database status.
- `POST /imports/upload` — upload one or more `.xls/.xlsx` files.
- `POST /imports/local` — import ignored workbooks from `data/local/source`.
- `GET /dashboard` — summary metrics.
- `GET /classes` — normalized classes and sessions.
- `GET/POST /constraints` — list and create hard/soft constraints.
- `POST /optimization/run` — solve assignments with CP-SAT.
- `GET /assignments` — latest assignments.
- `GET /conflicts` — validation and optimization issues.
- `GET /exports/latest` — download the latest formatted workbook.

Interactive OpenAPI documentation is available at `/docs`.

