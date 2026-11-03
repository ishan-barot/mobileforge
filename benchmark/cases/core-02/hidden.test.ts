import { describe, expect, it } from "vitest";
import { wasteFlags } from "../src/flags";
import { bill } from "./fixtures";

const today = new Date("2026-10-29T12:00:00Z");

describe("expired promos", () => {
  it("no flag once the promo has passed", () => {
    expect(wasteFlags(bill({ promoEndDate: "2026-10-01" }), today).map((f) => f.kind)).not.toContain("promo_ending");
  });
  it("still flags promos inside the window", () => {
    expect(wasteFlags(bill({ promoEndDate: "2026-12-01" }), today).map((f) => f.kind)).toContain("promo_ending");
  });
  it("ignores promos beyond 60 days", () => {
    expect(wasteFlags(bill({ promoEndDate: "2027-03-01" }), today).map((f) => f.kind)).not.toContain("promo_ending");
  });
});
