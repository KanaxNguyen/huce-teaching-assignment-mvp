import { describe, expect, it } from "vitest";

import { filterApplicableDrafts, getPreferenceSortRank } from "../src/features/dashboard/preference-context";
import type { PreferenceDraft } from "../src/types/api";

describe("preference rejection and sorting", () => {
  const makeDraft = (id: number, status: PreferenceDraft["status"], lecturerId: number = 1): PreferenceDraft => ({
    id,
    batch_id: 1,
    draft_kind: "CONSTRAINT",
    lecturer_id: lecturerId,
    lecturer: "Nguyễn Văn A",
    lecturer_code: "GV01",
    context_type: "TEACHING",
    constraint_type: "UNAVAILABLE",
    day_scope: "T2",
    periods: [1, 2, 3],
    hardness: "hard",
    weight: 1,
    target: {},
    participant_codes: [],
    source_file: "test.xlsx",
    source_sheet: "Sheet1",
    source_row: 5,
    source_cell: "C5",
    confidence: "HIGH",
    needs_review: status === "NEEDS_REVIEW",
    status,
  });

  it("assigns sort ranks correctly: Actionable (0) -> Confirmed (1) -> Rejected (2)", () => {
    expect(getPreferenceSortRank({ status: "DRAFT" })).toBe(0);
    expect(getPreferenceSortRank({ status: "NEEDS_REVIEW" })).toBe(0);
    expect(getPreferenceSortRank({ status: "CONFIRMED" })).toBe(1);
    expect(getPreferenceSortRank({ status: "REJECTED" })).toBe(2);
  });

  it("sorts drafts under lecturer view in order: Actionable -> Confirmed -> Rejected", () => {
    const drafts: PreferenceDraft[] = [
      makeDraft(1, "CONFIRMED"),
      makeDraft(2, "REJECTED"),
      makeDraft(3, "NEEDS_REVIEW"),
      makeDraft(4, "DRAFT"),
      makeDraft(5, "CONFIRMED"),
      makeDraft(6, "REJECTED"),
    ];

    drafts.sort((a, b) => getPreferenceSortRank(a) - getPreferenceSortRank(b));

    const statuses = drafts.map((d) => d.status);
    expect(statuses[0]).toMatch(/^(NEEDS_REVIEW|DRAFT)$/);
    expect(statuses[1]).toMatch(/^(NEEDS_REVIEW|DRAFT)$/);
    expect(statuses[2]).toBe("CONFIRMED");
    expect(statuses[3]).toBe("CONFIRMED");
    expect(statuses[4]).toBe("REJECTED");
    expect(statuses[5]).toBe("REJECTED");
  });

  it("strictly excludes REJECTED drafts from applicable solver inputs", () => {
    const confirmed = makeDraft(1, "CONFIRMED");
    const rejected = makeDraft(2, "REJECTED");
    const needsReview = makeDraft(3, "NEEDS_REVIEW");

    const applicable = filterApplicableDrafts([confirmed, rejected, needsReview]);
    expect(applicable).toHaveLength(1);
    expect(applicable[0].id).toBe(1);
  });

  it("supports rejection metadata and reversible restoration", () => {
    const draft = makeDraft(10, "CONFIRMED");
    // Simulate rejection
    const rejectedDraft: PreferenceDraft = {
      ...draft,
      status: "REJECTED",
      rejected_at: "2026-09-06T12:00:00Z",
      rejected_reason: "Không phù hợp với khối lượng kỳ này",
    };
    expect(rejectedDraft.status).toBe("REJECTED");
    expect(rejectedDraft.rejected_reason).toBe("Không phù hợp với khối lượng kỳ này");

    // Simulate restoration (REJECTED -> NEEDS_REVIEW)
    const restoredDraft: PreferenceDraft = {
      ...rejectedDraft,
      status: "NEEDS_REVIEW",
      rejected_at: null,
      rejected_reason: null,
    };
    expect(restoredDraft.status).toBe("NEEDS_REVIEW");
    expect(restoredDraft.rejected_at).toBeNull();
    expect(restoredDraft.rejected_reason).toBeNull();
  });
});
