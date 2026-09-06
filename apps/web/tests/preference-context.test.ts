import { describe, expect, it } from "vitest";

import { preferenceRuleTypesForContext } from "../src/features/dashboard/preference-context";

describe("preference draft context", () => {
  it("keeps teaching and seminar rule choices separate and never offers one mixed rule", () => {
    expect(preferenceRuleTypesForContext("TEACHING")).toContain("UNAVAILABLE");
    expect(preferenceRuleTypesForContext("TEACHING")).not.toContain("SEMINAR_NOTE");
    expect(preferenceRuleTypesForContext("SEMINAR")).toEqual(["SEMINAR_COMMITMENT", "SEMINAR_NOTE"]);
    expect(preferenceRuleTypesForContext("MIXED")).toEqual([]);
  });
});
