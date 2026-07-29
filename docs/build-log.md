# Build log

- 2026-07-30: audited the input folder and local toolchain.
- 2026-07-30: copied five workbooks into ignored local storage without modifying originals.
- 2026-07-30: attempted Figma metadata and read-only page discovery; both returned `INVALID_ARGUMENT`.
- 2026-07-30: Docker was unavailable; container configuration is included but cannot be executed locally.
- 2026-07-30: parsed 314 valid schedule rows into 175 classes and 314 sessions; preserved 36 locked classes and proposed 64 merged pairs.
- 2026-07-30: frontend production build passed; frontend lint, typecheck, and unit test passed.
- 2026-07-30: backend test suite passed (3 tests), real local import returned HTTP 200, and CP-SAT produced an optimal 175-class assignment.
- 2026-07-30: generated and rendered both sheets of the real Excel export for visual verification.
- 2026-07-30: in-app browser connection could enumerate the browser but could not claim a session tab; browser visual QA was replaced by the automated Playwright test path.
- 2026-07-30: Playwright E2E passed locally using the installed Chrome channel; CI installs Chromium explicitly.
- 2026-07-30: Python ruff check passed after formatting.
- 2026-07-30: created private GitHub repository `KanaxNguyen/huce-teaching-assignment-mvp`, set `main` as the default branch, and pushed the verified source.
