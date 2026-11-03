import { describe, expect, it } from "vitest";
import { matchPlans, type Plan } from "../src/matcher";
import { bill } from "./fixtures";

const base = { network: "5G", url: "https://example.com", lastVerified: "2026-11-01" };
const plan = (id: number, monthlyPrice: number, dataGB: number | null): Plan => ({ ...base, id, carrier: "X", name: `P${id}`, monthlyPrice, dataGB });

describe("current cost includes overage", () => {
  it("counts overage toward what they pay now", () => {
    const m = matchPlans(bill({ overageCharges: 30, dataUsedGB: 4 }), [plan(1, 60, 10)]);
    expect(m.map((p) => p.id)).toEqual([1]);
    expect(m[0].savingsPerYear).toBe(300);
  });
  it("no overage, same as before", () => {
    expect(matchPlans(bill({ dataUsedGB: 4 }), [plan(1, 25, 10)])[0].savingsPerYear).toBe(360);
  });
});
