import { describe, expect, it } from "vitest";
import { redact } from "../src/redact";

describe("postal codes", () => {
  it("masks with no space", () => {
    expect(redact("Toronto ON M5B2K3")).toBe("Toronto ON [POSTAL]");
  });
  it("masks lowercase", () => {
    expect(redact("m5b 2k3")).toBe("[POSTAL]");
  });
  it("still masks with a space or dash", () => {
    expect(redact("M5B 2K3 M5B-2K3")).toBe("[POSTAL] [POSTAL]");
  });
});
