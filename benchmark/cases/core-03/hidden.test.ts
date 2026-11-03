import { describe, expect, it } from "vitest";
import { wasteFlags } from "../src/flags";
import { bill } from "./fixtures";

const today = new Date("2026-10-29T12:00:00Z");

describe("zero usage", () => {
  it("flags 0 GB used", () => {
    const f = wasteFlags(bill({ dataUsedGB: 0 }), today).find((x) => x.kind === "low_usage");
    expect(f?.message).toBe("You used 0 GB of a 50 GB plan");
  });
  it("doesn't flag when usage is unknown", () => {
    expect(wasteFlags(bill({ dataUsedGB: null }), today).map((f) => f.kind)).not.toContain("low_usage");
  });
  it("doesn't flag unlimited plans", () => {
    expect(wasteFlags(bill({ dataCapGB: null, dataUsedGB: 0 }), today).map((f) => f.kind)).not.toContain("low_usage");
  });
});
