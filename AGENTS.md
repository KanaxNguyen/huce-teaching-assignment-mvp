# AGENTS.md - Workspace Instructions for Antigravity

Before performing any tasks or modifications in this repository, agents must read and follow:
👉 `docs/ANTIGRAVITY_PROJECT_CONTEXT.md`

## Critical Safety Rules

1. **Preserve Frozen Releases**: Never rewrite history, amend commits, or delete tags (`mvp-v1-frozen-20260905`, `mvp-v1.1-frozen-20260905`).
2. **Inspect Git Diff Before Edits**: Always run `git status` and `git diff` before modifying files to preserve in-progress work.
3. **Never Infer Unresolved Lecturer as Global**: Unresolved lecturer preferences must remain in `NEEDS_REVIEW` state and must never become global active constraints.
4. **Solver Objective Requires Explicit Approval**: Never change the solver objective hierarchy, weights, or fairness formulation without explicit user approval.
5. **Partial Meeting-Level Merge is Deferred**: TeachingGroup-level merge is supported when confirmed; do not implement meeting-level partial merges without explicit approval.
6. **Production Deployment Requires Approval**: Never trigger production deployments or run destructive database migrations.
7. **Protect Real Excel Fixtures**: Treat all original Excel fixtures and historical workbooks as read-only.
