import { describe, expect, it } from "vitest";
import { wasteFlags } from "../src/flags";
import { bill } from "./fixtures";

const today = new Date("2026-10-29T12:00:00Z");

describe("overage message", () => {
  it("always two decimals", () => {
    const f = wasteFlags(bill({ overageCharges: 19.5 }), today).find((x) => x.kind === "overage");
    expect(f?.message).toBe("$19.50 in overage charges this month");
  });
  it("whole dollars too", () => {
    const f = wasteFlags(bill({ overageCharges: 20 }), today).find((x) => x.kind === "overage");
    expect(f?.message).toBe("$20.00 in overage charges this month");
  });
});
