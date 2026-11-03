import { describe, expect, it } from "vitest";
import { redact } from "../src/redact";

describe("dotted phones", () => {
  it("masks dots", () => {
    expect(redact("call 416.555.0142 now")).toBe("call [PHONE] now");
  });
  it("still masks dashes and spaces", () => {
    expect(redact("416-555-0142 / 416 555 0142")).toBe("[PHONE] / [PHONE]");
  });
  it("leaves decimals in money alone", () => {
    expect(redact("Total $145.20")).toBe("Total $145.20");
  });
});
