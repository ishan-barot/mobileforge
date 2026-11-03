import { describe, expect, it } from "vitest";
import { wasteFlags } from "../src/flags";
import { bill } from "./fixtures";

const today = new Date("2026-10-29T12:00:00Z");

describe("low usage threshold", () => {
  it("exactly 25% is not low usage", () => {
    expect(wasteFlags(bill({ dataUsedGB: 12.5 }), today).map((f) => f.kind)).not.toContain("low_usage");
  });
  it("just under 25% is low usage", () => {
    expect(wasteFlags(bill({ dataUsedGB: 12.4 }), today).map((f) => f.kind)).toContain("low_usage");
  });
});
