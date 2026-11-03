import { describe, expect, it } from "vitest";
import { matchPlans, type Plan } from "../src/matcher";
import { bill } from "./fixtures";

const base = { network: "5G", url: "https://example.com", lastVerified: "2026-11-01" };
const plan = (id: number, monthlyPrice: number, dataGB: number | null): Plan => ({ ...base, id, carrier: "X", name: `P${id}`, monthlyPrice, dataGB });

describe("unlimited plans", () => {
  it("recommends a cheaper unlimited plan", () => {
    expect(matchPlans(bill({ dataUsedGB: 40 }), [plan(1, 50, null)]).map((p) => p.id)).toEqual([1]);
  });
  it("ranks unlimited by savings like any other", () => {
    const m = matchPlans(bill({ dataUsedGB: 4 }), [plan(1, 50, null), plan(2, 25, 10)]);
    expect(m.map((p) => p.id)).toEqual([2, 1]);
    expect(m[1].savingsPerYear).toBe(60);
  });
});
