import { describe, expect, it } from "vitest";
import { matchPlans, type Plan } from "../src/matcher";
import { bill } from "./fixtures";

const base = { network: "5G", url: "https://example.com", lastVerified: "2026-11-01" };
const plan = (id: number, monthlyPrice: number, dataGB: number | null): Plan => ({ ...base, id, carrier: "X", name: `P${id}`, monthlyPrice, dataGB });

describe("unknown usage", () => {
  it("assumes the full cap", () => {
    const ids = matchPlans(bill({ dataUsedGB: null, dataCapGB: 50 }), [plan(1, 25, 15), plan(2, 45, 60)]).map((p) => p.id);
    expect(ids).toEqual([2]);
  });
  it("zero usage is a real number, not missing", () => {
    expect(matchPlans(bill({ dataUsedGB: 0 }), [plan(1, 20, 2)]).map((p) => p.id)).toEqual([1]);
  });
  it("10 GB default when cap and usage are both missing", () => {
    expect(matchPlans(bill({ dataUsedGB: null, dataCapGB: null }), [plan(1, 25, 12), plan(2, 20, 10)]).map((p) => p.id)).toEqual([1]);
  });
});
