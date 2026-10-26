# HUCE review — 2026-10-05

TASK_ID: HUCE-METRICS-HISTORY-20261005. OWNER: REVIEW_AGENT/BACKEND_AGENT (one agent). Scope: metrics and investigation; historical capability overwrite/merge awaits decisions. Original HUCE repository: `/Users/mac/AI/Huce_timetable/huce-teaching-assignment-mvp`; isolated verification copy: `/Users/mac/BUILD_PHASE/HUCE-review-20261005`. P-068 unchanged.

## Verified findings

- The supplied Paper-TKB (1).pdf, page 7, Table 3 claims 308/308 for three scenarios including 85 locked classes. It provides neither soft penalty values nor timing nor runtime configuration. Those results were not reproduced here.
- Current solver allows unassigned classes, penalizing them in the objective. OPTIMAL means optimum of that model, not necessarily complete assignment or publication readiness.
- Objective terms: unassigned classes × 1,000,000; participating lecturers with zero assignments × 100,000; workload spread × 1,000; soft preference penalties. Existing architecture documentation omits the zero-assignment term; IMPLEMENTATION / DESIGN MISMATCH. No weights or behavior changed.
- Current review UI displays lecturer capabilities; the backend PUT /api/v1/lecturers/{lecturer_id}/capabilities edits a global lecturer/course pair, not a semester-scoped capability.
- A feasible manual candidate shown in the screenshot is not sufficient evidence of a complete feasible solution or of yesterday's identical inputs. The screenshot's precise failure has NOT BEEN REPRODUCED. No explanation about yesterday is asserted.

## Measured diagnostic run

Source: `output/experiments/current_import.json`. Input SHA-256 hashes are recorded there. Fresh import of the specified original schedule and detailed preference workbook; no manual approval of drafts; no merge confirmation. Not a replication of any paper scenario.

| Item | Measurement |
|---|---:|
| Accepted schedule rows | 286 |
| Teaching groups | 158 |
| Assigned groups | 132 |
| Unassigned groups | 26 |
| Preference drafts | 74 |
| Solver status | optimal |
| Solver wall time | 0.279886 seconds |
| Solve pipeline elapsed | 0.437479 seconds |
| Soft preference penalty | 0 |
| Unassigned penalty | 26,000,000 |
| Workload spread penalty | 360,000 |
| Zero-assignment lecturer penalty | 0 |
| Total objective | 26,360,000 |

Configuration: 30-second limit, 8 search workers, seed 1, confirm_merged=False. Python 3.12.14; OR-Tools 9.15.6755; Darwin arm64, 10 logical CPUs. These are local single-run measurements. The zero soft penalty is not evidence of satisfied approved preferences: this scenario did not manually approve drafts. Do not insert these numbers into Table 3 as if they described 308 classes or 85 locks.

The new summary.experiment records configuration/environment, solver wall time, elapsed solve time, best objective bound and separate objective components on completed solves. Previous saved runs cannot recover unrecorded timings. An early blocked run does not acquire experiment metrics. Existing summary/score fields and the objective remain unchanged; no migration.

## Verification

- TDD: new metric test initially failed with KeyError 'experiment'; after patch all 13 phase3 solver tests passed.
- Full backend suite executed in verification copy: seven failures and one skip. All seven failure messages are missing fixtures or an unavailable test database; no expected results changed. Full output: output/experiments/backend_suite.txt.
- Failed tests: test_phase5_real_data.py::{test_real_huce_schedule_and_preferences_normalize_without_losing_rows,test_real_data_import_solve_problem_export_round_trip_and_persistence}; test_regression.py::{test_hard_unavailable_not_bypassed,test_export_unassigned_fallback,test_dashboard_metrics,test_solver_maximum_valid_solution}; test_template_multirow.py::test_real_xls_multirow_header_golden.
- Diagnostic importer → solver → persisted run/assignments executed locally. Staging UI, production, prior-run equivalence and the paper's three scenarios NOT VERIFIED.
- Git diff --check passed in original HUCE repository after applying the patch.

## User decision and outstanding scope

DECISION-ID HUCE-HISTORY-MODE-20261005: user requests explicit overwrite or combine options for lecturer courses from the prior semester. Modules affected: historical import, lecturer review and capability handling. Source choice and application scope are not yet approved.

NEED_USER_DECISION:
1. Semester-only capability changes versus updating the current global catalog. Semester-only needs an explicit schema/contract migration plan; it must not be silently emulated by overwriting global records.
2. Combine behavior when historical evidence includes a currently forbidden course: preserve prohibition and flag conflict, or permit again.

PROPOSED DESIGN: preview differences before apply; explicit overwrite/combine modes; never infer confirmed permission solely from historical teaching evidence. This is a proposal, not approved behavior. No historical overwrite/combine implementation or lecturer permission edits have been applied.

AGENT_HANDOFF: metrics code/test applied to original HUCE repository; reproducible diagnostic script and JSON delivered. Next owner: project owner decides scope/conflict behavior; BACKEND_AGENT/FRONTEND_AGENT implement the approved capability flow; TEST_AGENT reproduces the screenshot using identical dataset/state and reruns the paper scenarios before updating PDF. Remaining risk: historical evidence is not authorization, and an optimal partial assignment must not be advertised as fully assigned.
