import type { PreferenceDraft } from "@/src/types/api";

export const teachingDraftTypes = ["UNAVAILABLE", "AVOID_PERIOD", "PREFERRED_PERIOD", "PREFERRED_DAYS", "AVOID_DAYS", "PREFER_LOW_WORKLOAD", "PREFER_COMPACT_SCHEDULE", "PREFER_CONSECUTIVE_PERIODS", "MIN_CLASSES", "MAX_CLASSES", "MAX_SESSIONS_PER_DAY", "MAX_DAYS_PER_WEEK", "MIN_FREE_MORNING_PER_WEEK", "REQUIRED_ASSIGNMENT", "FORBIDDEN_ASSIGNMENT", "RAW_NOTE"];
export const seminarDraftTypes = ["SEMINAR_COMMITMENT", "SEMINAR_NOTE"];

export function preferenceRuleTypesForContext(context: "TEACHING" | "SEMINAR" | "MIXED" | null) {
  return context === "SEMINAR" ? seminarDraftTypes : context === "TEACHING" ? teachingDraftTypes : [];
}

export function getPreferenceSortRank(item: Pick<PreferenceDraft, "status">): number {
  if (item.status === "REJECTED") return 2;
  if (item.status === "CONFIRMED") return 1;
  if (item.status === "INTERPRETED") return 2;
  return 0; // Actionable: DRAFT, NEEDS_REVIEW, etc.
}

export function filterApplicableDrafts(drafts: PreferenceDraft[]): PreferenceDraft[] {
  return drafts.filter(
    (item) =>
      item.status === "CONFIRMED" &&
      !item.needs_review &&
      !!item.lecturer_id &&
      !item.applied_constraint_id &&
      !item.applied_seminar_id
  );
}
