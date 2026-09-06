# Preference Normalization V2

Preference V2 separates uploaded text from active solver constraints:

`Excel row/clause → normalized draft → human review → confirmed draft → atomic apply → constraint`

The importer never sends parser output directly to the solver. Only confirmed, active constraints affect assignment. Unsupported or incomplete statements remain visible as `NEEDS_REVIEW`, with their original text and source cell preserved.

## Input formats

- `STRUCTURED_V2` is detected from the `Nguyen_vong_GV` sheet and required headers, not from the filename.
- Other workbooks use the deterministic legacy parser. Each source cell is split into atomic clauses; no clause is silently dropped.
- Lecturer identity resolution uses lecturer code, then a confirmed alias, then one exact normalized full-name match. An unresolved identity never becomes a global constraint.

The canonical workbook is `data/fixtures/Template_Nguyen_vong_Giang_v2.xlsx`. It contains `Huong_dan`, `Nguyen_vong_GV`, `Seminar_Shared`, and `Danh_muc`.

## Explicit context

`context_type` is independent from lecturer ownership and has three values:

- `TEACHING`: a lecturer's teaching-schedule preference.
- `SEMINAR`: seminar information owned by the selected lecturer; this is not global/shared by implication.
- `MIXED`: input containing both meanings. It must be split into at least two atomic drafts before apply.

A human-confirmed context takes precedence over parser inference and is preserved on re-import. Older drafts with a null context remain readable as `TEACHING`.

`SEMINAR_NOTE`, `RAW_NOTE`, incomplete seminar timing, unsupported rules, and unresolved lecturer identities cannot be applied to the solver. Shared seminars are created only from the explicit `Seminar_Shared` structure.

## Hard/soft semantics

Hardness and weight are separate. `SOFT` with weight `1.0` remains soft; `HARD` does not derive its meaning from weight. Period ranges are inclusive, so `4–6` means periods 4, 5, and 6.

No external language model is required. If model assistance is added later, its output must remain a draft validated by the same schema and human-review gate.
