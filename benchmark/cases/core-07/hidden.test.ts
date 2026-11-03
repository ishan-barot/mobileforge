import { describe, expect, it } from "vitest";
import { matchPlans, type Plan } from "../src/matcher";
import { bill } from "./fixtures";

const base = { network: "5G", url: "https://example.com", lastVerified: "2026-11-01" };
const plan = (id: number, monthlyPrice: number, dataGB: number | null): Plan => ({ ...base, id, carrier: "X", name: `P${id}`, monthlyPrice, dataGB });

describe("headroom", () => {
  it("requires 20% above usage", () => {
    const ids = matchPlans(bill({ dataUsedGB: 9 }), [plan(1, 25, 10), plan(2, 30, 15)]).map((p) => p.id);
    expect(ids).toEqual([2]);
  });
  it("accepts a plan right at the headroom line", () => {
    expect(matchPlans(bill({ dataUsedGB: 10 }), [plan(1, 25, 12)]).map((p) => p.id)).toEqual([1]);
  });
});
