import { describe, expect, it } from "vitest";
import { matchPlans, type Plan } from "../src/matcher";
import { bill } from "./fixtures";

const base = { network: "5G", url: "https://example.com", lastVerified: "2026-11-01" };
const plan = (id: number, monthlyPrice: number, dataGB: number | null): Plan => ({ ...base, id, carrier: "X", name: `P${id}`, monthlyPrice, dataGB });

describe("savings precision", () => {
  it("keeps cents", () => {
    expect(matchPlans(bill({ dataUsedGB: 4 }), [plan(1, 25.05, 10)])[0].savingsPerYear).toBe(359.4);
  });
  it("whole numbers unchanged", () => {
    expect(matchPlans(bill({ dataUsedGB: 4 }), [plan(1, 25, 10)])[0].savingsPerYear).toBe(360);
  });
});
