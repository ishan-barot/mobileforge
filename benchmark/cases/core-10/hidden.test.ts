import { describe, expect, it } from "vitest";
import { matchPlans, type Plan } from "../src/matcher";
import { bill } from "./fixtures";

const base = { network: "5G", url: "https://example.com", lastVerified: "2026-11-01" };
const plan = (id: number, monthlyPrice: number, dataGB: number | null): Plan => ({ ...base, id, carrier: "X", name: `P${id}`, monthlyPrice, dataGB });

describe("ranking", () => {
  it("biggest savings first", () => {
    const m = matchPlans(bill({ dataUsedGB: 4 }), [plan(1, 50, 10), plan(2, 25, 10), plan(3, 40, 10)]);
    expect(m.map((p) => p.id)).toEqual([2, 3, 1]);
  });
  it("ties go to more data", () => {
    const m = matchPlans(bill({ dataUsedGB: 4 }), [plan(1, 30, 10), plan(2, 30, 20)]);
    expect(m.map((p) => p.id)).toEqual([2, 1]);
  });
});
