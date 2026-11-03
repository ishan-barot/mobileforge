import { describe, expect, it } from "vitest";
import { redact } from "../src/redact";

describe("account label case", () => {
  it("masks uppercase labels", () => {
    const out = redact("ACCOUNT NO: 8841-2290-17");
    expect(out).not.toMatch(/8841/);
    expect(out).toContain("[ACCOUNT]");
  });
  it("masks mixed case", () => {
    expect(redact("Acct # 55-1234-99")).not.toMatch(/1234/);
  });
});
