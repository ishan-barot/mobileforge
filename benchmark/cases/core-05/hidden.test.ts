import { describe, expect, it } from "vitest";
import { wasteFlags } from "../src/flags";
import { bill } from "./fixtures";

const today = new Date("2026-10-29T12:00:00Z");

describe("repeat overage", () => {
  it("one-off when last month had none", () => {
    const kinds = wasteFlags(bill({ overageCharges: 20 }), today, bill({ overageCharges: 0 })).map((f) => f.kind);
    expect(kinds).toContain("overage");
    expect(kinds).not.toContain("repeat_overage");
  });
  it("repeat when both months had overage", () => {
    expect(wasteFlags(bill({ overageCharges: 20 }), today, bill({ overageCharges: 5 })).map((f) => f.kind)).toContain("repeat_overage");
  });
  it("one-off with no previous bill", () => {
    expect(wasteFlags(bill({ overageCharges: 20 }), today).map((f) => f.kind)).toContain("overage");
  });
});
