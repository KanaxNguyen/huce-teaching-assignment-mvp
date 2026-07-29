# Architecture

The MVP is a two-service monorepo:

- **Web:** Next.js + React + TypeScript. It renders the Minimal SaaS shell and calls the API directly.
- **API:** FastAPI + SQLAlchemy + SQLite. It owns Excel ingestion, validation, constraints, merged-class proposals, optimization, and Excel export.

The importer retains source file/sheet/row metadata and original values. Existing lecturer assignments become locked. The optimizer works on a class (or confirmed merged group) as an indivisible unit and uses CP-SAT to enforce hard conflicts while minimizing weighted soft-constraint violations and load imbalance.

Real workbooks live only in ignored local folders. Anonymous fixtures are used by tests and CI.

