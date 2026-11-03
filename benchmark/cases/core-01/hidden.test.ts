import { describe, expect, it } from "vitest";
import { wasteFlags } from "../src/flags";
import { bill } from "./fixtures";

const today = new Date("2026-10-29T12:00:00Z");

describe("promo countdown", () => {
  it("rounds partial days up", () => {
    const f = wasteFlags(bill(), today).find((x) => x.kind === "promo_ending");
    expect(f?.message).toContain("23 days");
  });
  it("says 0 days on the last day", () => {
    const f = wasteFlags(bill({ promoEndDate: "2026-10-29" }), new Date("2026-10-29T00:00:00Z")).find((x) => x.kind === "promo_ending");
    expect(f?.message).toContain("0 days");
  });
  it("still yearly-izes the promo", () => {
    const f = wasteFlags(bill(), today).find((x) => x.kind === "promo_ending");
    expect(f?.extraPerYear).toBe(180);
  });
});
