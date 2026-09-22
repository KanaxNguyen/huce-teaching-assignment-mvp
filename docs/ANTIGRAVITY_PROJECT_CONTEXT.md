# Antigravity Project Context & System Documentation

> **Status Reference**: This document factually reflects the codebase state as of September 6, 2026. Every item is marked with its true technical lifecycle state: `[IMPLEMENTED]`, `[IN PROGRESS]`, or `[PLANNED]`.

---

## 1. Project Purpose

The HUCE Teaching Assignment & Timetable Management application is a specialized university scheduling system for the Mathematics Department (Tổ Bộ môn Toán) at Hanoi University of Civil Engineering (HUCE / Trường Đại học Xây dựng Hà Nội).

The application **does not** generate the entire university timetable from scratch. Instead, the central university schedule (meetings, weekdays, period blocks, rooms, calendar dates) is already established and imported from university portal exports. The system's primary mission is to:
1. Ingest existing timetable schedules (`.xls` legacy and `.xlsx`).
2. Ingest, parse, and normalize lecturer teaching preferences and seminar constraints.
3. Solve the optimal, conflict-free assignment of qualified faculty members to university teaching groups (`TeachingGroup` / `ClassSection`) using Google OR-Tools CP-SAT.
4. Support interactive human-in-the-loop adjustments (locking, manual overrides, conflict analysis via Problem Log).
5. Export publication-ready Excel workbooks preserving authentic university templates and department matrix schedules.

---

## 2. Actual Repository Structure

The project is structured as a monorepo containing a Python/FastAPI backend and a Next.js frontend:

```
huce-teaching-assignment-mvp/
├── .env.example                       # Staging and local environment configuration template
├── .gitignore                         # Git exclusion rules
├── Makefile                           # Development convenience targets
├── README.md                          # Project overview and runbooks
├── alembic.ini                        # Database migration configuration
├── docker-compose.yml                 # Local container orchestration
├── package.json                       # Monorepo scripts (pnpm workspace)
├── pnpm-lock.yaml                     # Locked node dependencies
├── pnpm-workspace.yaml                # Workspace definitions
├── vercel.json                        # Vercel deployment build & routing configuration
├── apps/
│   ├── api/                           # Backend FastAPI Application
│   │   ├── alembic/                   # Alembic migration revisions
│   │   │   ├── versions/
│   │   │   │   ├── 0001_semester_isolation.py
│   │   │   │   ├── 0002_domain_correctness.py
│   │   │   │   ├── 0003_human_in_loop.py
│   │   │   │   ├── 0004_v11_merge_status.py
│   │   │   │   ├── 0005_preference_normalization_v2.py
│   │   │   │   └── 0006_lecturer_reference.py  [IN PROGRESS]
│   │   │   └── env.py
│   │   ├── app/
│   │   │   ├── api/                   # REST routing and endpoints
│   │   │   │   └── routes.py          # Core API endpoints & preference draft lifecycle
│   │   │   ├── core/                  # Core settings and configuration
│   │   │   │   └── config.py          # Environment, storage paths, tokens
│   │   │   ├── db/                    # Database session & base declarative models
│   │   │   │   └── session.py         # SQLAlchemy engine, session maker, foreign key pragma
│   │   │   ├── exporters/             # Excel workbook generation
│   │   │   │   └── excel.py           # Detailed tabular and lecturer-week matrix export
│   │   │   ├── models/                # SQLAlchemy ORM entities
│   │   │   │   └── entities.py        # Domain entities, constraints, drafts, audit
│   │   │   ├── optimization/          # CP-SAT Constraint Programming Solver
│   │   │   │   └── solver.py          # Decision variables, hard/soft constraints, objective
│   │   │   ├── parsers/               # Workbook ingestion and parsing
│   │   │   │   ├── preferences.py     # Deterministic legacy clause parser & V2 structured parser
│   │   │   │   └── schedule.py        # HUCE portal schedule parser (.xls / .xlsx)
│   │   │   ├── schemas/               # Pydantic request/response schemas
│   │   │   │   └── api.py             # DTO definitions
│   │   │   ├── services/              # Domain services
│   │   │   │   ├── importer.py        # Schedule/preference ingestion & draft creation
│   │   │   │   ├── manual_assignment.py # Human override & incremental conflict checker
│   │   │   │   ├── readiness.py       # Pre-solve validation engine
│   │   │   │   └── template_detector.py # Output template header/column layout detector
│   │   │   ├── storage/               # Object storage abstraction
│   │   │   │   └── __init__.py        # Local filesystem vs S3 compatible storage
│   │   │   └── main.py                # FastAPI entrypoint, CORS, internal token middleware
│   │   └── tests/                     # Pytest suite (acceptance, solver, parser, migrations)
│   └── web/                           # Frontend Next.js Application
│       ├── app/
│       │   ├── api/backend/[...path]/ # Next.js Server-Side BFF proxy to FastAPI
│       │   │   └── route.ts
│       │   ├── layout.tsx             # Root layout and theme tokens
│       │   └── page.tsx               # Root application entry
│       ├── package.json               # Next.js 15, React 19, Vitest, Playwright
│       ├── src/
│       │   ├── features/dashboard/    # 6-Step workflow UI
│       │   │   ├── preference-context.ts # Context rule mappings (TEACHING vs SEMINAR)
│       │   │   ├── semester-workflow-app.tsx # Main dashboard application
│       │   │   └── semester-workflow.module.css # Styling & responsive tokens
│       │   ├── services/
│       │   │   └── api.ts             # API client (BFF vs direct)
│       │   ├── styles/                # CSS design tokens
│       │   └── types/
│       │       └── api.ts             # TypeScript API interfaces & preference draft types
│       └── tests/                     # Frontend Vitest unit tests
├── data/
│   ├── fixtures/                      # Test fixtures and canonical templates
│   │   └── Template_Nguyen_vong_Giang_v2.xlsx
│   └── local/                         # Local development sample data
├── docs/                              # Project documentation & release records
├── infra/                             # Dockerfiles for frontend and backend
├── scripts/                           # Utility scripts (template generation, anonymization)
└── storage/                           # Persistent local storage (db, uploads, exports)
```

---

## 3. Backend Architecture

- **Entrypoint**: `apps/api/app/main.py`. Initialises FastAPI, CORS middleware, directories, and internal token authentication middleware.
- **Configuration**: `apps/api/app/core/config.py`. Manages settings via Pydantic `BaseSettings`: environment (`development`, `staging`, `production`), `DATABASE_URL`, `STORAGE_BACKEND` (`local` / `s3`), `INTERNAL_API_TOKEN`, and upload/export directories.
- **DB Session Management**: `apps/api/app/db/session.py`. Creates SQLAlchemy engine and `SessionLocal`. For SQLite connections, it automatically enforces `PRAGMA foreign_keys=ON` upon connect.
- **Security & BFF Architecture**: In staging/production, requests from the browser hit the Next.js server-side route `/api/backend/[...path]`. The Next.js server forwards requests to FastAPI with the header `x-internal-api-key: <INTERNAL_API_TOKEN>`. FastAPI validates the token in `protect_internal_api` using constant-time string comparison (`compare_digest`). The token and backend internal URL are never exposed to client-side bundles.

---

## 4. Frontend Architecture

- **Framework**: Next.js 15.5 with React 19, TypeScript, and CSS Modules.
- **Semester Workflow (Steps 01 to 06)**:
  - **Step 01 (Semester Setup)**: Semester selection, creation, department head metadata.
  - **Step 02 (Import Files)**: Independent uploads of Schedule workbook and Preference workbook; template detection preview.
  - **Step 03 (Class & Merge Review)**: Inspection of imported TeachingGroups, review of merge candidates (same course, identical times, different class codes), confirmation/rejection of merged classes.
  - **Step 04 (Preference Review)**: Draft preference table, lecturer resolution, rule type/context adjustment, confidence filter, atomic draft apply gate.
  - **Step 05 (Assignment & Optimization)**: Run CP-SAT solver, view workload metrics, candidate inspector, manual assignment editor, lock toggles, Problem Log.
  - **Step 06 (Publication & Export)**: Readiness gate, download of Draft Excel or Final publication-ready Excel.

---

## 5. Database & Migration History

Database migrations are managed via Alembic:
1. `0001_semester_isolation` `[IMPLEMENTED]`: Establishes `semester_id` foreign key ownership across all transactional tables (`classes`, `constraints`, `seminars`, `assignments`, `optimization_runs`, `import_batches`, `output_template_profiles`, `validation_issues`). Enforces unique constraint on `classes(semester_id, course_id, class_code)`.
2. `0002_domain_correctness` `[IMPLEMENTED]`: Adds `lecturer_course_capabilities` table with `(lecturer_id, course_id)` unique constraint and `allowed`, `confirmed` flags.
3. `0003_human_in_loop` `[IMPLEMENTED]`: Adds `assignment_source` (`"IMPORTED"`, `"MANUAL"`, `"SOLVER"`) to `classes` and `source` to `assignments`.
4. `0004_v11_merge_status` `[IMPLEMENTED]`: Adds `merge_status` (`"single"`, `"candidate"`, `"confirmed"`, `"rejected"`) to `classes`.
5. `0005_preference_normalization_v2` `[IMPLEMENTED]`: Adds `normalized_preference_drafts` table to decouple raw imported preferences from solver-visible constraints.
6. `0006_lecturer_reference` `[IN PROGRESS]`: Adds `lecturer_aliases`, `lecturer_semester_profiles`, `historical_evidence`, and `lecturer_identity_audit` tables; adds `profile_type` to `output_template_profiles`; relaxes strict uniqueness on `lecturers.canonical_name` to accommodate homonyms disambiguated by lecturer code.

---

## 6. Solver Architecture (Google OR-Tools CP-SAT)

The optimization engine resides in `apps/api/app/optimization/solver.py`:
- **Decision Variables**:
  - `x[group_id, lecturer_id]`: Boolean variable for assigning lecturer to teaching group.
  - `unassigned[group_id]`: Boolean variable for unassigned teaching groups.
  - `choice_vars`: Boolean variables for selecting alternative time slots for shared seminars.
  - `violation_*`: Bounded integer variables for soft constraint deviations.
  - Workload metrics: `max_load`, `min_load`.
- **Candidate Eligibility**:
  - A lecturer is an eligible candidate for a group if and only if they possess an active, confirmed capability in `lecturer_course_capabilities` (`allowed=True` and `confirmed=True`).
- **Conflict Prevention**:
  - Overlap is calculated across weekday, period interval, active calendar week sets, and date ranges.
  - If two groups overlap, no lecturer may be assigned to both unless `merged_confirmed=True` and they share `merged_group_id`.
- **Locked Handling**:
  - Only groups with `locked_assignment=True` freeze the assigned lecturer in the solver. An assignment with `assignment_source="MANUAL"` whose lock is false remains re-optimizable.
- **Objective Function Hierarchy**:
  $$\text{Minimize } \left( \sum \text{unassigned} \times 1{,}000{,}000 + (\text{max\_load} - \text{min\_load}) \times 1{,}000 + \sum \text{soft\_penalties} \right)$$
  - Priority 1: Zero unassigned classes.
  - Priority 2: Workload fairness (minimizing credit spread).
  - Priority 3: Minimizing soft preference penalties.
  > **CRITICAL RULE**: Do NOT casually alter the objective hierarchy or weights.

---

## 7. Core Domain Concepts & Semantics

- **TeachingGroup (`ClassSection`)**: The fundamental unit of assignment. Corresponds to a class course section (e.g., "Giải tích 1 - 71KT4").
- **Meeting (`ClassSession`)**: An individual scheduled meeting belonging to a `TeachingGroup`. A group may have 1 to 3 meetings per week. Assignment happens at the `TeachingGroup` level, so all child meetings share the same lecturer.
- **Conflict Detection**: Two meetings conflict if and only if:
  1. Same weekday (`weekday == weekday`).
  2. Overlapping periods (`not (left.end_period < right.start_period or right.end_period < left.start_period)`).
  3. Overlapping active calendar weeks (`set(left.active_weeks) & set(right.active_weeks)`).
  4. Overlapping date ranges (if dates are specified).
- **Provenance vs. Lock Rule**:
  - `assignment_source` records provenance: `"IMPORTED"`, `"MANUAL"`, `"SOLVER"`.
  - Provenance **never** implies a freeze.
  - Only `locked_assignment == True` locks a class during solver runs.
- **Merge Semantics**:
  - Merged classes must share the same course, identical meeting timings, and explicit human confirmation (`merge_status == "confirmed"`).
  - True partial meeting-level merge is **not** currently supported and is deferred.

---

## 8. Import Workflow

- **Schedule Import**:
  - Ingests `.xls` or `.xlsx` portal schedule files.
  - Cleans strings, normalizes class codes, decodes week patterns (e.g. `"1234 678"` -> weeks 1,2,3,4,6,7,8).
  - Groups identical `(course_code, class_code)` into one `ClassSection` with multiple child `ClassSession` meetings.
  - Identifies merge candidates when different classes share exact course, weekday, period, and room.
- **Preference Import**:
  - Decoupled from schedule upload.
  - Inspects workbook structure: detects `STRUCTURED_V2` if sheet `Nguyen_vong_GV` is present; otherwise falls back to deterministic legacy parser.
  - Generates `NormalizedPreferenceDraft` rows.
  - Ambiguous or unsupported items are flagged as `NEEDS_REVIEW`.
  - Does **not** insert active `Constraint` rows directly into solver scope.

---

## 9. Lecturer Identity & Resolution

- **Resolution Hierarchy**:
  1. Exact lecturer code (e.g. `[00187]` or `GV001`).
  2. Confirmed alias from `lecturers.aliases` or `lecturer_aliases`.
  3. Single unique normalized full name match.
- **Dangerous Failure Mode**:
  - In legacy MVP code, an unresolved lecturer could result in `lecturer_id=None`, which the solver or constraint engine could inadvertently interpret as a global constraint.
  - **Under Preference V2 `[IMPLEMENTED]`**: An unresolved lecturer identity sets `needs_review=True` on the draft and is **strictly blocked** from being applied as an active constraint (`apply_preference_drafts` raises HTTP 422 if `not item.lecturer_id`).

---

## 10. Preferences & Normalization V2

- **Draft State Machine**:
  `Raw File Row → Normalized Draft (DRAFT / NEEDS_REVIEW) → Human Confirmation (CONFIRMED) → Apply → Active Constraint`
- **Context Distinction**:
  - `TEACHING`: Teaching schedule availability or preference (e.g. unavailable Tuesday morning).
  - `SEMINAR`: Lecturer's seminar commitment or note.
  - `MIXED`: Statement combining seminar and teaching requests (e.g. "T2,4 có lịch seminar nên xin dạy gọn T3,5,6,7"). Must be split into atomic drafts before application.
- **Supported Active Types**: `UNAVAILABLE`, `AVOID_PERIOD`, `PREFERRED_PERIOD`, `MIN_CLASSES`, `MAX_CLASSES`, `MAX_SESSIONS_PER_DAY`, `MAX_DAYS_PER_WEEK`, `REQUIRED_ASSIGNMENT`, `FORBIDDEN_ASSIGNMENT`, `SEMINAR_COMMITMENT`.
- **Review Notes**: `RAW_NOTE` and `SEMINAR_NOTE` can never be applied directly to the solver.

---

## 11. Seminar System

- **Lecturer-Specific Seminar Commitment**:
  - Expressed via `SEMINAR_COMMITMENT` with `context_type="SEMINAR"` owned by a specific lecturer.
  - Solver treats the slot as a hard or soft busy block for that lecturer.
- **Shared Department Seminar Event**:
  - Modeled in the `Seminar` entity.
  - Multiple faculty participants (`members: list[int]`).
  - Alternative candidate time slots (`alternatives: list[dict]`).
  - Solver selects exactly one common conflict-free slot for all attending members.

---

## 12. Manual Constraints

- **Existing UI/API `[IMPLEMENTED]`**:
  - Create/edit draft constraints via `POST/PATCH /preference-drafts`.
  - Manual creation modal supporting `TEACHING`, `SEMINAR`, `MIXED`.
  - Real-time preview of impacted classes.
- **Planned Dimensions `[PLANNED]`**:
  - Explicit `target_scope`: `LECTURER`, `COURSE`, `LECTURER_COURSE`, `SEMINAR`.

---

## 13. Assignment Lifecycle

1. **Imported**: Initial lecturer imported from portal schedule file (`assignment_source="IMPORTED"`).
2. **Solver Assigned**: Generated by CP-SAT run (`assignment_source="SOLVER"`).
3. **Manual Override**: User reassigns teaching group via UI (`assignment_source="MANUAL"`). Evaluated by real-time feasibility checker (`check_assignment_change`).
4. **Locked**: User toggles lock (`locked_assignment=True`). Freezes assignment against subsequent solver runs.
5. **Unassigned**: When no eligible candidate or conflict-free slot exists. Highlighted in Problem Log.

---

## 14. Export System

- **Detailed Assignment Workbook `[IMPLEMENTED]`**:
  - Re-injects solver results into the original schedule template layout using source-row mapping (`OutputTemplateProfile`).
  - Fallback clean tabular export: sheet `"Phân công"` (tabular classes, credits, room, lecturer, lock status).
- **Lecturer-Week Matrix Workbook `[IMPLEMENTED (Clean) / PLANNED (Exact Template Profile)]`**:
  - Sheet `"TKB_Bo_Mon"` provides matrix: rows = lecturers, columns = weekdays (Thứ 2 to Chủ Nhật).
  - Each cell contains multi-line meeting blocks: Course name, class code, period range, room, date range.

---

## 15. Storage & Deployment

- **Storage Abstraction `[IMPLEMENTED]`**:
  - `apps/api/app/storage/__init__.py`.
  - `LocalStorageBackend`: Filesystem storage in `./storage/`.
  - `S3StorageBackend`: Persistent private bucket for staging/production (R2/S3/MinIO).
- **Deployment Topology `[IMPLEMENTED / VERIFIED]`**:
  - Frontend: Vercel (Next.js server-side BFF).
  - Backend: Railway / Docker (FastAPI with Uvicorn).
  - Database: PostgreSQL on Railway; SQLite for local development and offline testing.
  - Secret Isolation: Backend API token is kept strictly server-side; `NEXT_PUBLIC_` is never used for security tokens.

---

## 16. Period Domain Audit (1..15 vs. 1..12)

The university operational period domain spans **periods 1 through 15 inclusive**:
- **Morning**: Canonical blocks 1-3, 4-6 (Whole morning: 1-6).
- **Afternoon**: Canonical blocks 7-9, 10-12 (Whole afternoon: 7-12).
- **Evening**: Canonical block 13-15.
- **Irregular blocks**: Real schedules feature 1-5, 2-6, 13-15.

### Locations Currently Bound to 1..12 (Pending Migration to 1..15):
1. `apps/api/app/parsers/preferences.py`:
   - Line 145: `"ca ngay"` returns `range(1, 13)`. Must be updated to `range(1, 16)`.
   - Line 149: `"chieu"` returns `range(7, 13)`.
   - Line 151: `"toi"` returns `range(10, 13)`. Evening should map to `range(13, 16)` (periods 13-15).
2. `apps/api/app/optimization/solver.py`:
   - Line 174: `MAX_CONSECUTIVE_BLOCKS` enumerates only `((1, 3), (4, 6), (7, 9), (10, 12))`. Missing evening block `(13, 15)`.
3. `apps/api/app/services/manual_assignment.py`:
   - Line 61: `enumerate(((1, 3), (4, 6), (7, 9), (10, 12)))` and `range(4)`.
4. `apps/web/src/features/dashboard/semester-workflow-app.tsx`:
   - Line 804: Period dropdown options hardcoded to `["1-3", "4-6", "7-9", "10-12"]`. Missing `"13-15"`.
   - Line 815: `CalendarPreview` blocks hardcoded to `[[1, 3], [4, 6], [7, 9], [10, 12]]`. Missing evening block `[13, 15]`.

---

## 17. Real Excel Fixtures & Authoritative Input/Output Mapping

### Authoritative Pipeline Confirmed by User:

```
[INPUT FILES (in 'INPUT Gốc/')]
1. Phan_Cong_Giang_Day_HK1_2026_2027.xlsx   (Raw university schedule export: classes, meetings, rooms, weeks)
2. Nguyện vọng TKB 2026-2027.xlsx            (Raw department preference export: teacher wishes, seminar timing)
   └── (Optionally: Template_Nguyen_vong_Giang_v2.xlsx for Structured V2 input)

                    │
                    ▼ [HUCE Timetable Optimization Engine]
                    │

[DESIRED OUTPUT FILES (Confirmed from User Reference Image)]
1. phan-cong-giang-day-lich-hoc-to-bo-mon-03-09-2026.xls
   └── Detailed class schedule workbook matching the university portal format (335 rows, merged header rows 8-9, column 'Giảng viên' filled with [code]Name).
2. TKB-NCM Toan-Ky1-2026-2027.xlsx
   └── Department timetable matrix by Lecturer and Weekday ('TKB_Bo_Mon', 20 faculty rows, Monday through Sunday, multi-line cells with class, room, period range, date range, and shared seminar events).
```

### Detailed Fixtures Specification:

| Fixture Filename | Format | Location | Role & Schema Notes |
|---|---|---|---|
| `Nguyện vọng TKB 2026-2027.xlsx` | XLSX | `INPUT Gốc/` | **Authoritative Preference Input**: Free-text Vietnamese requests per weekday with informal aliases ("Thoan", "Cường", "X Linh", "Mai Hồng"). Header at row 3 (`Trang tính1`). |
| `Phan_Cong_Giang_Day_HK1_2026_2027.xlsx` | XLSX | `INPUT Gốc/` | **Authoritative Schedule Input**: 286 rows. Header at row 4 (`Phân Công Giảng Dạy`). Contains course codes, class codes, rooms, weeks, and initial lecturer codes in format `[00187]Phạm Đức Thoan`. |
| `phan-cong-giang-day-lich-hoc-to-bo-mon-03-09-2026.xls` | XLS | Workspace Root | **Target Output 1 (Detailed Schedule)**: 335 rows. Legacy portal export with 2-row merged header (rows 8-9). Authoritative university template for detailed assignment export. |
| `TKB-NCM Toan-Ky1-2026-2027.xlsx` | XLSX | Workspace Root | **Target Output 2 (Lecturer Matrix)**: 23 rows (`TKB_Bo_Mon`). Header at row 3. Rows = lecturers; columns = weekdays (Thứ 2 to Chủ Nhật). Multi-line schedule cells and seminar events. |
| `Template_Nguyen_vong_Giang_v2.xlsx` | XLSX | `INPUT Gốc/` & `data/fixtures/` | Canonical V2 structured template with data validations and dropdowns. |
| `DEMO_KET_QUA_MVP_HUCE.xlsx` | XLSX | Workspace Root | Existing MVP export demo with both tabular and matrix sheets. |

---

## 18. Release History

- `mvp-v1-frozen-20260905` (Commit `4ffbeec`): Frozen MVP v1 baseline release.
- `mvp-v1.1-frozen-20260905` (Commit `abe7844`): Frozen MVP v1.1 release with department workflow controls.
- Staging Deployments (Commits `1659fcd` through `a940361`): Railway persistent deployment, Vercel monorepo configuration, and template export disambiguation fixes.
- `checkpoint: preserve preference V2 normalization` (Commit `7655bef`): Checkpoint committing Preference V2 normalization pipeline.
- Current Working Tree: Uncommitted ORM entity additions for Lecturer Master lifecycle (`0006_lecturer_reference`).

---

## 19. Known Technical Debt & Business Limitations

1. **Partial Meeting-Level Merge**: Not supported. Merging is strictly at `TeachingGroup` level. Classes must share identical meetings across the entire semester.
2. **Historical Output Learning**: Currently limited to template mapping for export; does not yet extract historical capability, alias, or assignment intelligence into master profiles.
3. **Period 13-15 Evening Support**: Solver block constraints and frontend calendar do not yet include evening blocks.
4. **Lecturer Master CRUD**: No admin UI or REST endpoints exist yet for adding, editing, merging, or deactivating lecturers.

---

## 20. Critical Safety Rules for Future Agents

1. **Preserve Frozen Releases**: Never rewrite history, amend commits, or delete tags (`mvp-v1-frozen-20260905`, `mvp-v1.1-frozen-20260905`).
2. **Inspect Git Diff Before Edits**: Always run `git status` and `git diff` before modifying files to avoid overwriting ongoing work.
3. **Never Infer Unresolved Lecturer as Global**: A preference with an unmapped lecturer must remain `NEEDS_REVIEW` and **must never** be applied as a global solver constraint.
4. **Solver Objective Requires Explicit Approval**: Never change the objective hierarchy, multipliers, or fairness metrics without user sign-off.
5. **Partial Merge is Deferred**: Do not attempt to redesign meeting-level partial merges during incremental feature work.
6. **Production Deployment Requires Approval**: Never execute production deployment or run destructive database migrations.
7. **Protect Real Excel Fixtures**: Real fixture workbooks must be treated as read-only reference data.
