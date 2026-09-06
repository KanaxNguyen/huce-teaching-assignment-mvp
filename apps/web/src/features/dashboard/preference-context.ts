export const teachingDraftTypes = ["UNAVAILABLE", "AVOID_PERIOD", "PREFERRED_PERIOD", "PREFER_CONSECUTIVE_PERIODS", "MIN_CLASSES", "MAX_CLASSES", "MAX_SESSIONS_PER_DAY", "MAX_DAYS_PER_WEEK", "MIN_FREE_MORNING_PER_WEEK", "REQUIRED_ASSIGNMENT", "FORBIDDEN_ASSIGNMENT", "RAW_NOTE"];
export const seminarDraftTypes = ["SEMINAR_COMMITMENT", "SEMINAR_NOTE"];

export function preferenceRuleTypesForContext(context: "TEACHING" | "SEMINAR" | "MIXED") {
  return context === "SEMINAR" ? seminarDraftTypes : context === "TEACHING" ? teachingDraftTypes : [];
}
